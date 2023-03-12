# -------------------------------------------------------------------------------
#
#  X10mqtt gateway
#
#   This script allows for bridging between MQTT and X10.
#
#   It utilizes the 'heyu' command (https://www.heyu.org) for X10 control
#   and monitoring.
#
#   This was written and tested using a CM11a attached via a USB-to-Serial
#   adapter.  It may work with a CM17 Firecracker as well.
#
#   This does NOT support the USB devices like the SmartHome PowerLinc 1132B,
#   or the X10 CM15A.
#
#   This only allows ON and OFF commands to X10 appliance modules (or lamp modules).
#   Sorry, dimmer control is NOT supported.
#
# -------------------------------------------------------------------------------


import paho.mqtt.client as mqtt
import re
import subprocess
import os

try:
  broker = os.environ['MQTT_HOST']
except:
  print("Must define MQTT Host in configuration!")
  exit(1)
  
try:
  port = int(os.environ['MQTT_PORT'])
except:
  print("Must define MQTT port in configuration!")
  exit(1)
  
try:
  mqttuser = os.environ['MQTT_USER']
except:
  mqttuser = ""

try:
  mqttpass = os.environ['MQTT_PASSWORD']
except:
  mqttpass = ""

# rcvihc stores the house code from the monitor

rcvihc = ""

# cmdtopic for commands.  Housecode is appended.
# e.g. 'x10/cmd/A1' to command A1 device.
#
# Payload is either "ON" to turn on a unit, or "OFF" to turn it off
#
# Defaults to 'x10/cmd' if not defined
#
try:
  cmdtopic = os.environ['CMD_TOPIC']
except:
  cmdtopic = "x10/cmd"

#
# status topic is for status updates
#
# We set the payload to "ON" or "OFF" for status updates
# This was added to support X10 remote buttons in order to keep
# the switch/light state correct in Home Assistant.
#
try:
  stattopic = os.environ['STAT_TOPIC']
except:
  stattopic = "x10/stat"

#
# Whether a CM17A is in use
#
if os.getenv('USE_CM17') == 'true':
  cm17 = True
else:
  cm17 = False

#
# Execute Heyu command
# cmd is one of:
#   ON - turn on housecode
#   OFF - Turn off housecode
#
#
def execute(client, cmd, housecode):
  # For the CM11, send command to heyu as-is (ON or OFF)
  # For the CM17, we need to change it to FON or FOFF.
  heyucmd = cmd
  if cm17:
    if cmd.lower() == "on":
      heyucmd = "fon"
    if cmd.lower() == "off":
      heyucmd = "foff"
  result = subprocess.run(["heyu", heyucmd.lower(), housecode.lower()])
  if result.returncode:
    print("Error running heyu, return code: "+str(result.returncode))
  print("Device Status Update: "+stattopic+"/"+housecode.lower())
  client.publish(stattopic+"/"+housecode.lower(),cmd.upper(),retain=True)
  return (result.returncode)

#
# Execute heyu monitor
# This is a long-lived process that monitors for X10 changes,
# like from a remote control.
#


def monitor():
    popen = subprocess.Popen(["heyu","monitor"], stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)


#
# The monitor lines are broken out into 2 lines for one event:
#   rcvi addr unit - Declares the full unit number
#   rcvi func - The function on that unit
#

#
# Monitor rcvi addr unit - save the unit address in a variable for later
#
# Argument:  housecode, which is the housecode involved.  This is captured from the regex in the main loop and passed.
#

def rcviaddr(housecode):
  global rcvihc
  # Store the received housecode for when rcvifunc is received
  rcvihc = housecode

#
# Monitor rcvi func - the function that was applied to the housecode
#
# This happens after the 'rcvi addr unit', so the housecode that is stored
# from that is what is used.
#
# Argument:  func, which is the function (On or Off).  This is captured from the regex in the main loop and passed.
#

def rcvifunc(client,func):
  global rcvihc
  if rcvihc:
   print("Remote status change, publishing stat update: "+stattopic+"/"+rcvihc.lower()+" is now "+func.upper())
   client.publish(stattopic+"/"+rcvihc.lower(),func.upper(), retain=True)
   rcvihc = ""

#
# Define MQTT Connect Callback
#

def on_connect (client, userdata, flags, rc):

  # Set up MQTT subscription
  if rc:
    print("Error connecting to MQTT broker rc "+str(rc))

  print("Connected to MQTT broker, result code "+str(rc))
  client.subscribe(cmdtopic+"/+")

#
# Callback for MQTT message received
#

def on_message(client, userdata, message):

  # Determine the device from the topic
  # Topics are cmdtopic/dev, e.g. 'x10/cmd/A1'
  # So the last part is the device we want to control

  command = str(message.payload.decode('utf-8')).upper()
  print("Received: "+message.topic+" "+command)
  topiclist = message.topic.split("/")

  # Get the homecode and convert it to upper case
  hc = topiclist[len(topiclist)-1].upper()


  # Check that everything is right
  hcpattern = re.compile("^[A-P][0-9]+$")
  if command in ["ON", "OFF"] and hcpattern.match(hc):
    print("Sending X10 command to homecode "+hc)
    result = execute(client, command, hc)
  else:
    print("Invalid command or home code")

# ---------------------------
# Main program
# ---------------------------

# MQTT connect


print("Establishing MQTT to "+broker+" port "+str(port)+"...")
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

# Check if mqttuser or mqttpass is not blank
# If not, then configure the username and password

if mqttuser and mqttpass:
  print("(Using MQTT username "+mqttuser+")")
  client.username_pw_set(mqttuser,mqttpass)

try:
  client.connect(broker,port)
except:
  print("Connection failed. Make sure broker, port, and user is defined correctly")
  exit(1)

if cm17:
  print("CM17 is in use")

# Start the MQTT loop

print("Waiting for MQTT messages and monitoring for remote changes")
client.loop_start()

# We run 'heyu monitor' in the background to monitor for any X10 changes outside of us (e.g. X10 remotes)
# This way, we can send MQTT status changes if something does change.

# Regular expressions used to catch X10 updates, e.g. from X10 remotes, triggers on the module, or command line commands.
# See https://github.com/HeyuX10Automation/heyu/blob/902a4ef46d857de7e7fc157ea7c3f2562f4f1624/release_notes.txt#L527-L534
rercviaddr = re.compile(r"(?:rcvi|rcvt|sndc|snds|sndm|sndt) addr unit.+hu ([A-P][0-9]+)")
rercvifunc = re.compile(r"(?:rcvi|rcvt|sndc|snds|sndm|sndt) func.*(On|Off) :")


# Start the monitor process, which runs all the time.
# Catch any updates we care about so we can handle sending status updates via MQTT

for line in monitor():
  addrsearch = rercviaddr.search(line)
  funcsearch = rercvifunc.search(line)
  if addrsearch:
    rcviaddr(str(addrsearch.group(1)))
  if funcsearch:
    rcvifunc(client,str(funcsearch.group(1)))
