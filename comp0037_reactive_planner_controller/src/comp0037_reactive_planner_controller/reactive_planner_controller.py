# This class manages the key logic for the reactive planner and
# controller. This monitors the the robot motion.

import time
import rospy
import threading
from cell import CellLabel
from planner_controller_base import PlannerControllerBase
from comp0037_mapper.msg import *
from comp0037_reactive_planner_controller.aisle import Aisle

# from the definitions in occupancy_grid.py
BLOCKED = 1.0
FREE = 0.0
Y_OFFSET = 28
X_OFFSET = 16
BASE = (26,6)
# d = {number: [[BASE[0] + number * X_OFFSET, BASE[1] + row*Y_OFFSET] for row in range(3)] for number in range(5)}
aisle_to_goals_table = {x: [(BASE[0] + x * X_OFFSET, BASE[1] + y * Y_OFFSET) for y in range(3)] for x in range(5)}
print "Michael Debug:", aisle_to_goals_table

class ReactivePlannerController(PlannerControllerBase):

    def __init__(self, occupancyGrid, planner, controller):
        PlannerControllerBase.__init__(self, occupancyGrid, planner, controller)

        self.mapUpdateSubscriber = rospy.Subscriber('updated_map', MapUpdate, self.mapUpdateCallback)
        self.gridUpdateLock =  threading.Condition()
        self.aisleToDriveDown = None

        self._aisle_to_goals_table = aisle_to_goals_table # my note: replece it to a proper attr later !!!

    def mapUpdateCallback(self, mapUpdateMessage):

        # Update the occupancy grid and search grid given the latest map update
        self.gridUpdateLock.acquire()
        self.occupancyGrid.updateGridFromVector(mapUpdateMessage.occupancyGrid)
        self.planner.handleChangeToOccupancyGrid()
        self.gridUpdateLock.release()

        # If we are not currently following any route, drop out here.
        if self.currentPlannedPath is None:
            return

        self.checkIfPathCurrentPathIsStillGood()

    def checkIfPathCurrentPathIsStillGood(self):

        # This methods needs to check if the current path, whose
        # waypoints are in self.currentPlannedPath, can still be
        # traversed

        # If the route is not viable any more, call
        # self.controller.stopDrivingToCurrentGoal()
        # for wp in self.currentPlannedPath.waypoints:
        #     x,y = wp.coords
        #     status = self.occupancyGrid.getCell(x,y)
        #     if status == BLOCKED or status == 1: # check status from the continuously updating occupancy grid
        #         print 'coords = ', x, y, 'status = ', status, 'Now stop and replan' # debug del
        #         self.controller.stopDrivingToCurrentGoal() # stop the robot
        #         break
        pass

    # Choose the first aisle the robot will initially drive down.
    # This is based on the prior.
    def chooseInitialAisle(self, startCellCoords, goalCellCoords):
        return Aisle.C

    # Choose the subdquent aisle the robot will drive down
    def chooseAisle(self, startCellCoords, goalCellCoords):
        return Aisle.E

    # Return whether the robot should wait for the obstacle to clear or not.
    def shouldWaitUntilTheObstacleClears(self, startCellCoords, goalCellCoords):
        return False

    # This method will wait until the obstacle has cleared and the robot can move.
    def waitUntilTheObstacleClears(self):
        pass

    # Plan a path to the goal which will go down the designated aisle. The code, as
    # currently implemented simply tries to drive from the start to the goal without
    # considering the aisle.
    def planPathToGoalViaAisle(self, startCellCoords, goalCellCoords, aisle):
        # Note that, if the robot has waited, it might be tasked to drive down the
        # aisle it's currently on. Your code should handle this case.
        if self.aisleToDriveDown is None:
            self.aisleToDriveDown = aisle

        # Implement your method here to construct a path which will drive the robot
        # from the start to the goal via the aisle.
        # <Michael mod>
        goals_aisle = self._aisle_to_goals_table[aisle.value][:]
        # goals_aisle = self._correct_path_direction(startCellCoords, goals_aisle) # my note: probably no need. The assignment is build on a very complete static assumption already.
        goals_rest =  goals_aisle + [goalCellCoords] # my note: the complete goals forcing the pass through aisle

        planned_path = self._get_path(startCellCoords, goals_rest[0])
        if planned_path is None:
            return
        for i in range(1, len(goals_rest)): # note: assume it never exceeds bounds. ie. always has the padding goals_aisle
            currentPlannedPath = self._get_path(goals_rest[i-1], goals_rest[i])
            if currentPlannedPath is None: # ie. the whole path is invalid
                return # note: early termaination. Failure was logged by side effect

            planned_path.addToEnd(currentPlannedPath) # mynote: complete the whole path here

        print('Waypoints of the passing aisle path: ', planned_path)
        self.planner.searchGridDrawer.drawPathGraphicsWithCustomColour(planned_path, 'red')
        return planned_path
        # <Michael mod>


    # This method drives the robot from the start to the final goal. It includes
    # choosing an aisle to drive down and both waiting and replanning behaviour.
    # Note that driving down an aisle is like introducing an intermediate waypoint.
    def driveToGoal(self, goal):

        # Get the goal coordinate in cells
        goalCellCoords = self.occupancyGrid.getCellCoordinatesFromWorldCoordinates((goal.x,goal.y))

        # Set the start conditions to the current position of the robot
        pose = self.controller.getCurrentPose()
        start = (pose.x, pose.y)
        startCellCoords = self.occupancyGrid.getCellCoordinatesFromWorldCoordinates(start)

        # Work out the initial aisle to drive down
        aisleToDriveDown = self.chooseInitialAisle(startCellCoords, goalCellCoords)

        # Reactive planner main loop - keep iterating until the goal is reached or the robot gets
        # stuck.

        while rospy.is_shutdown() is False:

            # Plan a path from the robot's current position to the goal. This is called even
            # if the robot waited and used its existing path. This is more robust than, say,
            # stripping cells from the existing path.

            print 'Planning a new path: start=' + str(start) + '; goal=' + str(goal)

            # Plan a path using the current occupancy grid
            self.gridUpdateLock.acquire()
            self.currentPlannedPath = self.planPathToGoalViaAisle(startCellCoords, goalCellCoords, aisleToDriveDown)
            self.gridUpdateLock.release()

            # If we couldn't find a path, give up
            if self.currentPlannedPath is None:
                return False

            # Drive along the path towards the goal. This returns True
            # if the goal was successfully reached. The controller
            # should stop the robot and return False if the
            # stopDrivingToCurrentGoal method is called.
            goalReached = self.controller.drivePathToGoal(self.currentPlannedPath, \
                                                          goal.theta, self.planner.getPlannerDrawer())

            rospy.logerr('goalReached=%d', goalReached)

            # If we reached the goal, return
            if goalReached is True:
                return True

            # An obstacle blocked the robot's movement. Determine whether we need to
            # wait or replan.

            # Figure out where we are
            pose = self.controller.getCurrentPose()
            start = (pose.x, pose.y)
            startCellCoords = self.occupancyGrid.getCellCoordinatesFromWorldCoordinates(start)

            # See if we should wait
            waitingGame = self.shouldWaitUntilTheObstacleClears(startCellCoords, goalCellCoords)

            # Depending upon the decision, either wait or determine the new aisle
            # we should drive down.
            if waitingGame is True:
                self.waitUntilTheObstacleClears()
            else:
                aisleToDriveDown = self.chooseAisle(startCellCoords, goalCellCoords)

        return False

    # Michael add-ons
    def _correct_path_direction(self, start, goals_aisle):
        ''' very static part, the assumption of always passing an aisle only works for this assignment !!!!!!!!!'''
        if start[0] > goals_aisle[1][0]:
            return list(reversed(goals_aisle))
        return goals_aisle

    def _get_path(self, startCellCoords, goalCellCoords):
        '''
        Return:
        None - if fails; Planned Path Object - if sucess
        '''
        pathToGoalFound = self.planner.search(startCellCoords, goalCellCoords)
        # If we can't reach the goal, give up and return
        if pathToGoalFound is False:
            rospy.logwarn("Could not find a path to the goal at (%d, %d)", \
                            goalCellCoords[0], goalCellCoords[1])
            return None
        return self.planner.extractPathToGoal()
