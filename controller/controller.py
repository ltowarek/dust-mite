from pydualsense import pydualsense

def cross_pressed(state):
    print(state)

ds = pydualsense() # open controller
ds.init() # initialize controller

ds.cross_pressed += cross_pressed
ds.light.setColorI(255,0,0) # set touchpad color to red

ds.close() # closing the controller
