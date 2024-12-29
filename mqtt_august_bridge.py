import paho.mqtt.client as mqtt
import bluepy.btle as btle
import augustpy.lock
import json
import time
import threading
import logging
global lock
global lock_event


def onStatusUpdate(state):
    if state:
        logging.debug(f"Bridge lock status: {state}")
        client.publish("august/lock/state", state, retain=True) 

def onAvailabilityUpdate(state):
    if state == "online":
        lock_event.set()
    else:
        lock_event.clear()
    client.publish("august/lock/availability", state, retain=True) 
def onVoltageUpdate(state):
    if state:
        logging.debug(f"Bridge lock voltage: {state}")
        client.publish("august/lock/voltage", state) 
def lockConnect():
    if(lock.is_connected()):
        onAvailabilityUpdate("online")
        return True
    resp = lock.connect()
    if(resp):
        logging.info(f"Bridge connected to lock: {lock.name}")
        onAvailabilityUpdate("online")
    else:
        logging.warning(f"Bridge unable to connect to lock: {lock.name}")
        onAvailabilityUpdate("offline")
    return resp
def lockDisconnect():
    onAvailabilityUpdate("offline")

def onCmdUpdate(state):
    if not state:
        lockDisconnect()
        lockConnect()

def sendLockCmdWithResponse(query, responseHandler):
    resp = query()
    if(resp and responseHandler):
        responseHandler(resp)

def on_mqtt_client_connect(client, userdata, flags, rc):
    client.subscribe("august/lock/set")

def on_mqtt_message(client, userdata, message):
    if(str(message.payload.decode("utf-8")) == 'LOCK'):
            logging.info("Bridge got lock mqtt message!")
            sendLockCmdWithResponse(lock.force_lock, onCmdUpdate)
    elif(str(message.payload.decode("utf-8")) == 'UNLOCK'):
            logging.info("Bridge got unlock mqtt message!")
            sendLockCmdWithResponse(lock.force_unlock, onCmdUpdate)

config = None
with open("config/config.json", "r") as config_file:
    config = json.load(config_file)

lock_event = threading.Event()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1) 
client.username_pw_set(config["mqtt"]["mqtt_user"],config["mqtt"]["mqtt_password"]) # <== use this if your MQTT server requires authentication. If not, you can comment out this whole line.
client.connect(config["mqtt"]["broker_address"])

client.publish("august/bridge/availability", "online", retain=True)
client.on_message = on_mqtt_message
client.on_connect = on_mqtt_client_connect
client.loop_start()


locks = []
for lock_config in config["lock"]:
    lock = augustpy.lock.Lock(lock_config["bluetoothAddress"], lock_config["handshakeKey"], lock_config["handshakeKeyIndex"], onStatusUpdate)
    if "name" in lock_config:
        lock.set_name(lock_config["name"])
    locks.append(lock)
if not locks:
    raise Exception("No locks configured")
lock = locks[0]  ##sketch AF....


lockConnect()
while True:
    try:
        lock_event.wait(config["polling_interval_seconds"])
        lock_event.clear()
        sendLockCmdWithResponse(lock.getStatus, False)
        sendLockCmdWithResponse(lock.getVoltage, onVoltageUpdate)
    except Exception as e:
        print(f"An error occurred: {e}")

