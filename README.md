# Robot Localization Project
## By: Gabrielle Blake

### About the Project

The goal of this project was to find the location of a robot's pose in real time given an initial pose estimate, laser scan data,odometry data, and a known map, using a particle filter. The purpose of the particle filter is to find the robot's exact position however, given the noise and inaccuracy of the laser scan and odometry sensors. The cornerstones of this project included understanding how the particle filter algorithm worked, how poses and odometry are represented across coordinate frames, and working with Rviz, the Gazebo simulator, and ROS to implement and debug code. 

The particle filter involves the following steps:

1. Initialize a set of particles via random sampling
2. Update the particles using data from odometry
3. Reweight the particles based on their compatibility with the laser scan
4. Resample with replacement a new set of particles with probability proportional to their weights.
5. Update your estimate of the robot’s pose given the new particles. Update the map to odom transform.

---
How did you solve the problem? (Note: this doesn’t have to be super-detailed, you should try to explain what you did at a high-level so that others in the class could reasonably understand what you did).

This problem can be solved by implementing a particle filter algorithm to find the most likely location of the robot at a given time, taking into the account the noise of sensors. The idea behind a particle filter is that particles are initialized throughout a given map to represent many possible poses (position and orientation) of the robot. As the robot moves through space, the particles are also updated to move similarly but with some noise added to account for the sensor imperfection and include poses of where the robot actually is and not just where the odometry sensor says it is.
In order to evaluate the probability a given particle represents where the robot actually is, the laser scans the robot is publishing are superimposed onto the map from the frame of each particle and the similarities between these scans and the real scan are evaluated such that particles with scans that have high similarity to the real scan are given higher weights as they are more likely poses. The average pose is then the particle filter's best estimate of the robot's real pose.
This process is then repeated over and over such that particles are resampled according to their weights. So more particles are initialized in the next iteration in the areas of the map where particles with high weights from the previous iteration existed, until the particles converge around the area the robot is most likely to be.

A high level structure of how the particle filter was implemented in code is as follows:
1. Initialize a set of particles in the map frame via random sampling
2. Update the particles using data from robot's odometry in the odom frame
3. Reweight the particles based on their compatibility with the laser scan (which is in the baselink frame)
4. Resample with replacement a new set of particles with probability proportional to their weights.
5. Update the estimate of the robot’s pose given the new particles. Update the map to odom transform.

The key to solving this problem of where is the robot at any given time was implementing a particle filter.
---
Describe a design decision you had to make when working on your project and what you ultimately did (and why)? These design decisions could be particular choices for how you implemented some part of an algorithm or perhaps a decision regarding which of two external packages to use in your project.
---
What if any challenges did you face along the way?
---
What would you do to improve your project if you had more time?
---
Did you learn any interesting lessons for future robotic programming projects? These could relate to working on robotics projects in teams, working on more open-ended (and longer term) problems, or any other relevant topic.
Sample WriteupsPermalink