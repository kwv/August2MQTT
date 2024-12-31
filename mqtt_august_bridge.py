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
def lockConnect(force=False):
    if(lock.is_connected() and not force):
        onAvailabilityUpdate("online")
        return True
    resp = lock.connect()
    if(resp == True):
        logging.info(f"Bridge connected to lock: {lock.name}")
        onAvailabilityUpdate("online")
    else:
        logging.warning(f"Bridge unable to connect to lock: {lock.name}")
        onAvailabilityUpdate("offline")
    return resp
def lockDisconnect():
    onAvailabilityUpdate("offline")

def onCmdUpdate(state):
    if state == False:
        lockDisconnect()
        lockConnect(True)

def sendLockCmdWithResponse(query, responseHandler):
    # when an error occurs we will try to reconnect to the lock, and retry the command
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = query()
            if resp and responseHandler:
                responseHandler(resp)
                break
            elif resp == False:
                logging.error(f"Command failed: {query}")
                raise Exception(f"Command failed: {query}")
            
        except Exception as e:
            logging.error(f"An error occurred sending cmd: {e}, attempt {attempt + 1} of {max_retries}")
            if attempt < max_retries - 1:
                lockDisconnect()
                time.sleep(2)  # wait before retrying
                lockConnect(True)
                time.sleep(2)  # wait before retrying
            else:
                logging.error("Max retries reached, command failed.")

def on_mqtt_client_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe("august/lock/set")
    if reason_code > 0:
        # error processing
        logging.error(f"MQTT connection error: {reason_code}")
        sys.exit(1)

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

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) 
client.username_pw_set(config["mqtt"]["mqtt_user"],config["mqtt"]["mqtt_password"]) # <== use this if your MQTT server requires authentication. If not, you can comment out this whole line.
client.connect_async(config["mqtt"]["broker_address"])

client.publish("august/bridge/availability", "online", retain=True)
client.on_message = on_mqtt_message
client.on_connect = on_mqtt_client_connect
client.loop_start()



lock = augustpy.lock.Lock(config["lock"]["bluetoothAddress"], config["lock"]["handshakeKey"], config["lock"]["handshakeKeyIndex"], onStatusUpdate)
lock.set_name(config["lock"]["name"])


lockConnect()
while True:
    try:
        lock_event.wait(config["polling_interval_seconds"])
        lock_event.clear()
        sendLockCmdWithResponse(lock.getStatus, False)
        sendLockCmdWithResponse(lock.getVoltage, onVoltageUpdate)
    except Exception as e:
        print(f"An error occurred: {e}")

