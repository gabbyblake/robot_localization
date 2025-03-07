#!/usr/bin/env python3

""" This is the starter code for the robot localization project """

import rclpy
from threading import Thread
from rclpy.time import Time
from rclpy.node import Node
from robot_localization import occupancy_field
from std_msgs.msg import Header
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseArray, Pose, Point, Quaternion
from rclpy.duration import Duration
import math
from statistics import mode
import time
import numpy as np
from occupancy_field import OccupancyField
from helper_functions import TFHelper, draw_random_sample
from rclpy.qos import qos_profile_sensor_data
from angle_helpers import quaternion_from_euler

class Particle(object):
    """ Represents a hypothesis (particle) of the robot's pose consisting of x,y and theta (yaw)
        Attributes:
            x: the x-coordinate of the hypothesis relative to the map frame
            y: the y-coordinate of the hypothesis relative ot the map frame
            theta: the yaw of the hypothesis relative to the map frame
            w: the particle weight (the class does not ensure that particle weights are normalized
    """

    def __init__(self, x=0.0, y=0.0, theta=0.0, w=1.0):
        """ Construct a new Particle
            x: the x-coordinate of the hypothesis relative to the map frame
            y: the y-coordinate of the hypothesis relative ot the map frame
            theta: the yaw of KeyboardInterruptthe hypothesis relative to the map frame
            w: the particle weight (the class does not ensure that particle weights are normalized """ 
        self.w = w
        self.theta = theta
        self.x = x
        self.y = y

    def as_pose(self):
        """ A helper function to convert a particle to a geometry_msgs/Pose message """
        q = quaternion_from_euler(0, 0, self.theta)
        return Pose(position=Point(x=self.x, y=self.y, z=0.0),
                    orientation=Quaternion(x=q[0], y=q[1], z=q[2], w=q[3]))

    
    # TODO: define additional helper functions if needed

class ParticleFilter(Node):
    """ The class that represents a Particle Filter ROS Node
        Attributes list:
            base_frame: the name of the robot base coordinate frame (should be "base_footprint" for most robots)
            map_frame: the name of the map coordinate frame (should be "map" in most cases)
            odom_frame: the name of the odometry coordinate frame (should be "odom" in most cases)
            scan_topic: the name of the scan topic to listen to (should be "scan" in most cases)
            n_particles: the number of particles in the filter
            d_thresh: the amount of linear movement before triggering a filter update
            a_thresh: the amount of angular movement before triggering a filter update
            pose_listener: a subscriber that listens for new approximate pose estimates (i.e. generated through the rviz GUI)
            particle_pub: a publisher for the particle cloud
            last_scan_timestamp: this is used to keep track of the clock when using bags
            scan_to_process: the scan that our run_loop should process next
            occupancy_field: this helper class allows you to query the map for distance to closest obstacle
            transform_helper: this helps with various transform operations (abstracting away the tf2 module)
            particle_cloud: a list of particles representing a probability distribution over robot poses
            current_odom_xy_theta: the pose of the robot in the odometry frame when the last filter update was performed.
                                   The pose is expressed as a list [x,y,theta] (where theta is the yaw)
            thread: this thread runs your main loop
    """
    def __init__(self):
        super().__init__('pf')
        self.base_frame = "base_footprint"   # the frame of the robot base
        self.map_frame = "map"          # the name of the map coordinate frame
        self.odom_frame = "odom"        # the name of the odometry coordinate frame
        self.scan_topic = "scan"        # the topic where we will get laser scans from 

        self.n_particles = 500          # the number of particles to use

        self.d_thresh = 0.2             # the amount of linear movement before performing an update
        self.a_thresh = math.pi/6       # the amount of angular movement before performing an update


        #self.step = 1                   # what step/iteration of the filter are we on, increases by 1 with each resample

        # TODO: define additional constants if needed

        # pose_listener responds to selection of a new approximate robot location (for instance using rviz)
        # calls method self.update_initial_pose when there are updates to the 'initialpose' topic
        self.create_subscription(PoseWithCovarianceStamped, 'initialpose', self.update_initial_pose, 10)

        # publish the current particle cloud.  This enables viewing particles in rviz.
        self.particle_pub = self.create_publisher(PoseArray, "particlecloud", qos_profile_sensor_data)

        # laser_subscriber listens for data from the lidar
        self.create_subscription(LaserScan, self.scan_topic, self.scan_received, 10)

        # this is used to keep track of the timestamps coming from bag files
        # knowing this information helps us set the timestamp of our map -> odom
        # transform correctly
        self.last_scan_timestamp = None
        # this is the current scan that our run_loop should process
        self.scan_to_process = None
        # your particle cloud will go here
        self.particle_cloud = []
        # probability distributions for particle cloud
        self.x_distribution = []
        self.y_distribution = []
        self.theta_distribution = []
        self.weight_distribution = []

        self.current_odom_xy_theta = []
        self.occupancy_field = OccupancyField(self)
        self.transform_helper = TFHelper(self)

        # we are using a thread to work around single threaded execution bottleneck
        thread = Thread(target=self.loop_wrapper)
        thread.start()
        self.transform_update_timer = self.create_timer(0.05, self.pub_latest_transform)

    def pub_latest_transform(self):
        """ This function takes care of sending out the map to odom transform """
        if self.last_scan_timestamp is None:
            return
        postdated_timestamp = Time.from_msg(self.last_scan_timestamp) + Duration(seconds=0.1)
        self.transform_helper.send_last_map_to_odom_transform(self.map_frame, self.odom_frame, postdated_timestamp)

    def loop_wrapper(self):
        """ This function takes care of calling the run_loop function repeatedly.
            We are using a separate thread to run the loop_wrapper to work around
            issues with single threaded executors in ROS2 """
        while True:
            self.run_loop()
            time.sleep(0.1)

    def run_loop(self):
        """ This is the main run_loop of our particle filter.  It checks to see if
            any scans are ready and to be processed and will call several helper
            functions to complete the processing.
            
            You do not need to modify this function, but it is helpful to understand it.
        """
        if self.scan_to_process is None:
            return
        msg = self.scan_to_process

        (new_pose, delta_t) = self.transform_helper.get_matching_odom_pose(self.odom_frame,
                                                                           self.base_frame,
                                                                           msg.header.stamp)
        if new_pose is None:
            # we were unable to get the pose of the robot corresponding to the scan timestamp
            if delta_t is not None and delta_t < Duration(seconds=0.0):
                # we will never get this transform, since it is before our oldest one
                self.scan_to_process = None
            return
        
        # because turtlebot fram is different from NEATO frame
        (r, theta) = self.transform_helper.convert_scan_to_polar_in_robot_frame(msg, self.base_frame)
        #print("r[0]={0}, theta[0]={1}".format(r[0], theta[0]))
        # clear the current scan so that we can process the next one
        self.scan_to_process = None

        self.odom_pose = new_pose
        new_odom_xy_theta = self.transform_helper.convert_pose_to_xy_and_theta(self.odom_pose)
        #print("x: {0}, y: {1}, yaw: {2}".format(*new_odom_xy_theta))

        if not self.current_odom_xy_theta:
            self.current_odom_xy_theta = new_odom_xy_theta
        elif not self.particle_cloud:
            # now that we have all of the necessary transforms we can update the particle cloud
            self.initialize_particle_cloud(msg.header.stamp)
        elif self.moved_far_enough_to_update(new_odom_xy_theta):
            # we have moved far enough to do an update!
            print(len(self.particle_cloud))
            self.update_particles_with_odom()    # update based on odometry
            #self.publish_particles(msg.header.stamp)
            self.update_particles_with_laser(r, theta)   # update based on laser scan
            self.update_robot_pose()                # update robot's pose based on particles
            self.resample_particles()               # resample particles to focus on areas of high density
            
        # publish particles (so things like rviz can see them)
        self.publish_particles(msg.header.stamp)

    def moved_far_enough_to_update(self, new_odom_xy_theta):
        return math.fabs(new_odom_xy_theta[0] - self.current_odom_xy_theta[0]) > self.d_thresh or \
               math.fabs(new_odom_xy_theta[1] - self.current_odom_xy_theta[1]) > self.d_thresh or \
               math.fabs(new_odom_xy_theta[2] - self.current_odom_xy_theta[2]) > self.a_thresh

    def initialize_particle_cloud(self, timestamp, xy_theta=None):
        """ Initialize the particle cloud.
            Arguments
            xy_theta: a triple consisting of the mean x, y, and theta (yaw) to initialize the
                      particle cloud around.  If this input is omitted, the odometry will be used """
        if xy_theta is None:
            xy_theta = self.transform_helper.convert_pose_to_xy_and_theta(self.odom_pose)

        self.particle_cloud = []
        # x, y, and theta of the robot's initial pose
        x_position = xy_theta[0]
        y_position = xy_theta[1]
        theta = xy_theta[2]
        
        # lists that will hold each particle's x-position, y-position, and theta in the particle_cloud
        self.x_distribution = []
        self.y_distribution = []
        self.theta_distribution = []

        # every particle starts with an equal weight of 1.0
        self.weight_distribution = [1.0] * self.n_particles

        # get bounding box so every particle
        ((x_lower, x_upper), (y_lower, y_upper)) = self.occupancy_field.get_obstacle_bounding_box()

        # populate particle cloud with n particles
        for num in range(len(self.weight_distribution)):
            # randomly generate positions centered around the initial pose
            x = np.random.normal(x_position, 0.25)
            y = np.random.normal(y_position, 0.25)
            t = np.random.normal(theta, 20 * (2*math.pi / 360))

            # if particle is not within map, generate a new pose until it is
            while not ((x_lower < x < x_upper) and (y_lower < y < y_upper)):
                x = np.random.normal(x_position, 0.25)
                y = np.random.normal(y_position, 0.25)
           
            # update distribution arrays
            self.x_distribution.append(x)
            self.y_distribution.append(y)
            self.theta_distribution.append(theta)
            w = self.weight_distribution[num]
            # update particle cloud with new particle
            self.particle_cloud.append(Particle(x, y, t, w))


    
    def update_particles_with_odom(self):
        """ Update the particles using the newly given odometry pose.
            The function computes the value delta which is a tuple (x,y,theta)
            that indicates the change in position and angle between the odometry
            when the particles were last updated and the current odometry.
        """
        new_odom_xy_theta = self.transform_helper.convert_pose_to_xy_and_theta(self.odom_pose)
        # compute the change in x,y,theta since our last update
        if self.current_odom_xy_theta:
            old_odom_xy_theta = self.current_odom_xy_theta
            delta = (new_odom_xy_theta[0] - self.current_odom_xy_theta[0],
                     new_odom_xy_theta[1] - self.current_odom_xy_theta[1],
                     new_odom_xy_theta[2] - self.current_odom_xy_theta[2])

            self.current_odom_xy_theta = new_odom_xy_theta
        else:
            self.current_odom_xy_theta = new_odom_xy_theta
            return
        # compute robot's transformation in pose in the form of one rotation, a translation, and another rotation
        theta_1 = math.atan2(delta[1],delta[0]) - self.current_odom_xy_theta[2]
        r = math.sqrt((delta[0]**2) + (delta[1]**2))
        theta_2 = delta[2] - theta_1

        # update particles based on odom, but allow for inaccuracy of odometry
        for particle in self.particle_cloud:
            # add noise to transformation
            new_theta_1 = np.random.normal(theta_1, 3*(2* math.pi / 360))
            new_r = np.random.normal(r, 0.15)
            new_theta_2 = np.random.normal(theta_2, 3*(2* math.pi / 360))# maybe even 10 degrees

            # move particles
            particle.theta += new_theta_1
            particle.x += new_r * math.cos(particle.theta)
            particle.y += new_r * math.sin(particle.theta)
            particle.theta += new_theta_2


    def update_particles_with_laser(self, r, theta):
        """ Updates the particle weights in response to the scan data
            r: the distance readings to obstacles
            theta: the angle relative to the robot frame for each corresponding reading 
        """
        # clear weight array
        self.weight_distribution = []
        
        # create scan readings for each particle
        for particle in self.particle_cloud:
            particle.w = 0.0
            # evaluate each scan for the particle
            for angle in range(len(r)):
                # catch nan and infinite float values
                if not (math.isnan(r[angle]) or math.isinf(r[angle])):
                    
                    # rotate then translate the scans according to particle pose
                    x_pos = r[angle] * math.cos(theta[angle] + particle.theta) + particle.x
                    y_pos = r[angle] * math.sin(theta[angle] + particle.theta) + particle.y

                    # evaluate scan's similarity to real robot's scan
                    distance = self.occupancy_field.get_closest_obstacle_distance(x_pos, y_pos)
                    # if object is in the map
                    if not math.isnan(distance):
                        if distance == 0.0:
                            particle.w = particle.w + 1
            #update weight array
            self.weight_distribution.append(particle.w)

    def update_robot_pose(self):
        """ Update the estimate of the robot's pose given the updated particles.
            There are two logical methods for this:
                (1): compute the mean pose
                (2): compute the most likely pose (i.e. the mode of the distribution)
        """
        # first make sure that the particle weights are normalized
        #self.normalize_particles()


        # Method 1, mean pose
        mean_x = sum(self.x_distribution) / self.n_particles
        mean_y = sum(self.y_distribution) / self.n_particles
        mean_theta = sum(self.theta_distribution) / self.n_particles


        # Method 2, most likely pose
        #best_particle = mode(self.particle_cloud)
        # print(best_particle)
        # highest_weight = mode(self.particle_cloud)
        # index = self.weight_distribution.index(highest_weight)
        # best_particle = self.particle_cloud[index]
        #pose = self.xy_theta_to_pose(best_particle.x, best_particle.y, best_particle.theta)
    
        # a little hard coding to make the robot's pose a bit better
        if  0 < mean_theta < math.pi/2:
            extra_x = -0.1
            extra_y = -0.1
        elif math.pi/2 < mean_theta < math.pi:
            extra_x = 0.1
            extra_y = -0.1
        elif math.pi < mean_theta < 3*math.pi/2:
            extra_x = 0.1
            extra_y = 0.1
        elif 3*math.pi/2 < mean_theta < 2*math.pi:
            extra_x = -0.1
            extra_y = 0.1
        else:
            extra_x = 0.0
            extra_y = 0.0
        pose = self.xy_theta_to_pose(mean_x + extra_x, mean_y + extra_y, mean_theta)


        

        # just to get started we will fix the robot's pose to always be at the origin
        self.robot_pose = pose

        self.transform_helper.fix_map_to_odom_transform(self.robot_pose,
                                                        self.odom_pose)

    def resample_particles(self):
        """ Resample the particles according to the new particle weights.
            The weights stored with each particle should define the probability that a particular
            particle is selected in the resampling step.  You may want to make use of the given helper
            function draw_random_sample in helper_functions.py.
        """
        # normalize particle weights
        self.normalize_particles()
        new_particle_cloud = draw_random_sample(self.particle_cloud, self.weight_distribution, self.n_particles)
        self.particle_cloud = new_particle_cloud
        
        self.x_distribution = [particle.x for particle in self.particle_cloud]
        self.y_distribution = [particle.y for particle in self.particle_cloud]
        self.theta_distribution = [particle.theta for particle in self.particle_cloud]
        


    def update_initial_pose(self, msg):
        """ Callback function to handle re-initializing the particle filter based on a pose estimate.
            These pose estimates could be generated by another ROS Node or could come from the rviz GUI """
        xy_theta = self.transform_helper.convert_pose_to_xy_and_theta(msg.pose.pose)
        self.initialize_particle_cloud(msg.header.stamp, xy_theta)

    

    def normalize_particles(self):
        """ Make sure the particle weights define a valid distribution (i.e. sum to 1.0) """
        # normalize the weights
        norm = [float(w)/sum(self.weight_distribution) for w in self.weight_distribution]
        self.weight_distribution = norm
        
            

    def publish_particles(self, timestamp):
        particles_conv = []
        for p in self.particle_cloud:
            particles_conv.append(p.as_pose())
        # actually send the message so that we can view it in rviz
        self.particle_pub.publish(PoseArray(header=Header(stamp=timestamp,
                                            frame_id=self.map_frame),
                                  poses=particles_conv))


    def scan_received(self, msg):
        self.last_scan_timestamp = msg.header.stamp
        # we throw away scans until we are done processing the previous scan
        # self.scan_to_process is set to None in the run_loop 
        if self.scan_to_process is None:
            self.scan_to_process = msg

    def xy_theta_to_pose(self, x, y, theta):
        """ Convert x, y, and theta into a pose message. """
        q = quaternion_from_euler(0, 0, theta)
        return Pose(position=Point(x=x, y=y, z=0.0),
                    orientation=Quaternion(x=q[0], y=q[1], z=q[2], w=q[3]))

def main(args=None):
    rclpy.init()
    n = ParticleFilter()
    rclpy.spin(n)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
