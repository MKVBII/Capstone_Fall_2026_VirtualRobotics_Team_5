import time
from gpiozero import OutputDevice
import board
import busio
from adafruit_pca9685 import PCA9685

# --- This code goes on the Raspberry Pi ---
# The goal of this script is to make sure that the driving hardware works