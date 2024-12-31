import bluepy.btle as btle
import bluetooth._bluetooth as bluez
import bledist.blescan as blescan
import Cryptodome.Random
import threading
from . import session, util
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class keepLockAlive(threading.Thread):
	def __init__(self, thread_id, name, lock, interval):
		threading.Thread.__init__(self)
		self.thread_id = thread_id
		self.name = name
		self.lock = lock
		self._stop_event = threading.Event()
		self.interval = interval
	def run(self):
		logging.warning("Starting Lock Keep alive")
		while not self._stop_event.isSet(): #while exit flag is not set
			self._stop_event.wait(self.interval)
			if(not self._stop_event.isSet()):
				try:
					logging.debug("Sending keep alive") 
					self.lock.getStatus()
					#self.lock.led_G()
				except Exception as e:
					logging.warning("Lock keep alive failed. Reconnecting.")
					self.lock.disconnect()
					self.lock.connect()
		logging.warning("Lock keep alive exited")	
		#TODO: Add another event and defs setting and clearing the event to start/stop the lockalive

	def stop(self):
		self._stop_event.set()
		logging.warning("Exit flag sent to Lock keep alive")

class notificationProcessor_thread(threading.Thread):
    def __init__(self, lock):
        threading.Thread.__init__(self)
        self._stop_event = threading.Event()
        self.lock = lock
        self.session = lock.session
        self.daemon = True

    def run(self):
        try:
            while not self._stop_event.isSet(): #while exit flag is not set
                if(self.session.peripheral.waitForNotifications(1) and self._stop_event.isSet()==False):
                    logging.debug("HANDLE:::", self.session.delegate.cHandle)
                    temp = {} #dictionary
                    temp['cHandle'] = self.session.delegate.cHandle
                    temp['data'] = self.session.delegate.data
                    self.session.incomingData.append(temp)

                    # self.session.delegate.data = None
                    # self.session.delegate.cHandle = None

                    if((temp['data'][0] == 0xbb) and (temp['data'][1] == 0x02) and (temp['data'][4] == 0x02)): #incoming data is "status"
                        logging.debug("Status update received")
                        self.lock.status = temp['data'][8]
                        # self.lock.statusEvent.set()
                        strstatus = self.lock.parseStatus()
                        if (self.lock._onStatusUpdate != None):
                            self.lock._onStatusUpdate(strstatus)

                    if(self.session.delegate.cHandle != None):
                        logging.debug("data incoming!")
                        self.session.dataReady.set()
        except btle.BTLEDisconnectError:
            logging.error("Device disconnected unexpectedly!  Reconnecting...")
            self.lock.disconnect()
            self.lock.connect()

        logging.debug("Exiting notification processor thread.")

    def stop(self):
        logging.debug("Sending exit flag to notification processor thread.")
        self._stop_event.set()


class Lock:
    COMMAND_SERVICE_UUID        = btle.UUID("0000fe24-0000-1000-8000-00805f9b34fb")
    WRITE_CHARACTERISTIC        = btle.UUID("bd4ac611-0b45-11e3-8ffd-0800200c9a66")
    READ_CHARACTERISTIC         = btle.UUID("bd4ac612-0b45-11e3-8ffd-0800200c9a66")
    SECURE_WRITE_CHARACTERISTIC = btle.UUID("bd4ac613-0b45-11e3-8ffd-0800200c9a66")
    SECURE_READ_CHARACTERISTIC  = btle.UUID("bd4ac614-0b45-11e3-8ffd-0800200c9a66")

    def __init__(self, address, keyString, keyIndex, onStatusUpdate):
        self.address = address
        self.key = bytes.fromhex(keyString)
        self.key_index = keyIndex
        self.name = None
        self.notificationProcessor = None
        self.notificationProcessor_sec = None
        self.socket = bluez.hci_open_dev(0)

        self.peripheral = None
        self.session = None
        self.secure_session = None
        self.command_service = None
        self.is_secure = False
        self.conn_state = "disconnected"
        self.comm_state = "ready"
        self.status = 0
        self.statusEvent = threading.Event()
        self._onStatusUpdate = onStatusUpdate

    def set_name(self, name):
        self.name = name

    def connect(self):
        success = False
        i=0        
        while(not success and i<5): #was 10 tries
            try:
                self.peripheral = btle.Peripheral(self.address)
                if self.name is None:
                    self.name = self.peripheral.addr

                self.session = session.Session(self,self.peripheral)
                self.secure_session = session.SecureSession(self, self.peripheral, self.key_index)
                #self.notificationProcessor = threading.Thread(target=notificationProcessor_thread, args=(1,self.session), daemon=True)
                #self.notificationProcessor_sec = threading.Thread(target=notificationProcessor_thread, args=(2,self.secure_session), daemon=True)

                self.command_service = self.peripheral.getServiceByUUID(self.COMMAND_SERVICE_UUID)

                characteristics = self.command_service.getCharacteristics()
                #descs = characteristic.getDescriptors()
                for characteristic in characteristics:
                    if characteristic.uuid == self.WRITE_CHARACTERISTIC:
                        self.session.set_write(characteristic)
                        #print("Handle: " + characteristic.handle)
                        #print("ValHandle: " + characteristic.getHandle())
                    elif characteristic.uuid == self.READ_CHARACTERISTIC:
                        self.session.set_read(characteristic)
                        #descs = characteristic.getDescriptors()
                        #for desc in descs:
                            #print("found  desc: " + str(desc.uuid))
                            #str_uuid = str(desc.uuid).lower()
                            #if str_uuid.startswith("00002902"):
                                #mcu_sub_handle = desc.handle
                                #mcu_sub_handle = 21
                                #print("*** Found MCU subscribe handle: " + str(mcu_sub_handle))
                    elif characteristic.uuid == self.SECURE_WRITE_CHARACTERISTIC:
                        self.secure_session.set_write(characteristic)
                        logging.debug("Set Secure Write")
                    elif characteristic.uuid == self.SECURE_READ_CHARACTERISTIC:
                        self.secure_session.set_read(characteristic)
                        logging.debug("Set Secure Read")
                        #descs = characteristic.getDescriptors()
                        #for desc in descs:
                            #print("found  desc: " + str(desc.uuid))
                            #str_uuid = str(desc.uuid).lower()
                            #if str_uuid.startswith("00002902"):
                                #sec_sub_handle = desc.handle
                                #sec_sub_handle = 26
                                #print("*** Found SEC subscribe handle: " + str(sub_handle))

                #start wait for notification thread here
                #self.notificationProcessor.start()
                #self.notificationProcessor_sec.start()

                response = self.peripheral.writeCharacteristic(26, b'\x02\x00', withResponse=True)
                logging.debug("Subscription SEC request response: %s", response)

                response = self.peripheral.writeCharacteristic(21, b'\x02\x00', withResponse=True)
                logging.debug("Subscription MCU request response: %s", response)

                #self.session.notificationProcessor.start()
                #self.secure_session.notificationProcessor.start()

                #descs = self.peripheral.getDescriptors()
                #for desc in descs:
                #    print("  desc: " + str(desc))
                #    str_uuid = str(desc.uuid).lower()
                    #if str_uuid.startswith("00002902"):
                    #    print("*** Found subscribe handle: " + str(subscribe_handle))

                self.secure_session.set_key(self.key)
                #print("hello")
                #print(self.session.read_characteristic.supportsRead())

                response = None
                ii=0
                while(response == None and ii<10):
                    handshake_keys = Cryptodome.Random.get_random_bytes(16)
                    ii+=1
                    # Send SEC_LOCK_TO_MOBILE_KEY_EXCHANGE
                    cmd = self.secure_session.build_command(0x01)
                    util._copy(cmd, handshake_keys[0x00:0x08], destLocation=0x04)
                    response = self.secure_session.execute(cmd)
                    logging.debug(response)
                    success = True
            except KeyboardInterrupt:
                quit()
            except btle.BTLEDisconnectError:
                logging.warning("Connection probably failed")
                success = False
                time.sleep(0.5)
            i+=1

        if(success):
            if response[0x00] != 0x02:
                raise Exception("Unexpected response to SEC_LOCK_TO_MOBILE_KEY_EXCHANGE: " +
                                response.hex())

            self.is_secure = True
            self.session.is_secure = True

            session_key = bytearray(16)
            util._copy(session_key, handshake_keys[0x00:0x08])
            util._copy(session_key, response[0x04:0x0c], destLocation=0x08)
            self.session.set_key(session_key)
            self.secure_session.set_key(session_key)

            # Send SEC_INITIALIZATION_COMMAND
            cmd = self.secure_session.build_command(0x03)
            util._copy(cmd, handshake_keys[0x08:0x10], destLocation=0x04)
            response = self.secure_session.execute(cmd)
            if response[0] != 0x04:
                raise Exception("Unexpected response to SEC_INITIALIZATION_COMMAND: " +
                                response.hex())

        if(success and self.is_secure):
            self.peripheral.writeCharacteristic(26, b'\x00\x00', withResponse=False) #disable notifications from SEC? don't care anymore...
            # logging.info("Subscription SEC request response: %s", response)
            self.session.dataReady.clear()
            #self.session.notificationProcessor = notificationProcessor_thread(self)
            #self.session.notificationProcessor.start()
            self.conn_state = "connected"
            if not hasattr(self, 'keepAlive') or not self.keepAlive.is_alive():
                self.keepAlive = keepLockAlive(33, "lock keep alive", self, 60)
                self.keepAlive.start()
            # blescan.hci_le_set_conn_parameters(self.socket, handle = 0x0040, min_interval = 0x0027, max_interval = 0x0028, latency = 0x000F, sup_timeout = 0x0136) # 420 ms timeout
            #0x0027 in ms is 39.0625ms, 0x0028 in ms is 40.625ms, 0x000F in ms is 10.625ms, 0x0136 in ms is 310.625ms
            blescan.hci_le_set_conn_parameters(self.socket, handle = 0x0040, min_interval = 0x0027, max_interval = 0x0028, latency = 0x001E, sup_timeout = 0x0BB8) # 3000ms timeout in hex is 0x0BB8, 1000ms latency in hex is 0x001E
            logging.info("Connected to lock: %s", self.name)
            return True
        return False

    def force_lock(self):
        if self.session is None:
            raise Exception("Session is None! force_lock failed.")
        cmd = self.session.build_command(0x0b)

        try:
            response = self.session.execute(cmd)
        except btle.BTLEDisconnectError:
            logging.error("Device disconnected unexpectedly during force_lock!")
            self.disconnect()
            return False

        return response

    def force_unlock(self):

        if self.session is None:
            raise Exception("Session is None! force_unlock failed.")
        cmd = self.session.build_command(0x0a)

        try:
            response = self.session.execute(cmd)
        except btle.BTLEDisconnectError:
            logging.error("Device disconnected unexpectedly during force_unlock!")
            self.disconnect()
            return False

        # blescan.hci_le_set_conn_parameters(self.socket, handle = 0x0040, min_interval = 0x0027, max_interval = 0x0028, latency = 0x000F, sup_timeout = 0x0136) # 420 ms timeout
        return response


    def lock(self):
        if self.getStatus() == 'unlocked':
            return self.force_lock()

        return True

    def unlock(self):
        if self.getStatus() == 'locked':
            return self.force_unlock()

        return True

    def wait_start(self):
        self.session.notificationProcessor = notificationProcessor_thread(self)
        self.session.notificationProcessor.start()
    
        return True

    def wait_stop(self):
        self.session.notificationProcessor.stop()
        self.session.notificationProcessor.join()
        return True

    def setParam(self,param,val1,val2):
        cmd = bytearray(0x12)
        cmd[0x00] = 0xee
        cmd[0x01] = 0x03
        #cmd[0x03] = 0x0c #checksum?
        cmd[0x04] = param
        cmd[0x08] = val1
        cmd[0x09] = val2
        cmd[0x10] = 0x02
        if self.session is None:
            raise Exception("Session is None! setParam failed.")
        response = self.session.execute(cmd)
        logging.debug(response.hex())

    def getParam(self,param):
        cmd = bytearray(0x12)
        cmd[0x00] = 0xee
        cmd[0x01] = 0x04
        #cmd[0x03] = 0x0c #checksum?
        cmd[0x04] = param
        cmd[0x10] = 0x02
        if self.session is None:
            raise Exception("Session is None! getParam failed.")
        response = self.session.execute(cmd)
        logging.debug(response.hex())

    def getStatus(self):
        cmd = bytearray(0x12)
        cmd[0x00] = 0xee
        cmd[0x01] = 0x02
        #cmd[0x03] = 0x0c #checksum?
        cmd[0x04] = 0x02
        #cmd[0x10] = 0x02

        self.statusEvent.clear()
        try:
            if self.session is None:
                raise Exception("Session is None! getStatus failed.")
            response = self.session.execute(cmd)
        except btle.BTLEDisconnectError:
            logging.error("Device disconnected unexpectedly during getStatus!")
            self.disconnect()
            return False

        if(response != None):
            self.status = response[0x08]
            return self.parseStatus()
        else:
            logging.warning("Got NONE status :(")
            return False

    def parseStatus(self):
        strstatus = 'unknown'
        if self.status == 0x02:
            strstatus = 'unlocking'
        elif self.status == 0x03:
            strstatus = 'unlocked'
        elif self.status == 0x04:
            strstatus = 'locking'
        elif self.status == 0x05:
            strstatus = 'locked'

        if strstatus == 'unknown':
            logging.warning("Unrecognized status code: %s", hex(self.status))

        return strstatus

    def getVoltage(self):
        cmd = bytearray(0x12)
        cmd[0x00] = 0xee
        cmd[0x01] = 0x02
        #cmd[0x03] = 0x0c #checksum?
        #cmd[0x04] = 0x05 #battery %
        cmd[0x04] = 0x0F #batteryVoltage
        #cmd[0x10] = 0x02

        # response = self.session.execute(cmd)


        try:
            if self.session is None:
                raise Exception("Session is None! getVoltage failed.")
            response = self.session.execute(cmd)
        except btle.BTLEDisconnectError:
            logging.error("Device disconnected unexpectedly during getVoltage!")
            self.disconnect()
            return False

        if(response != None):
            return (response[0x09] * 256) + response[0x08]            
        else:
            logging.warning("Got NONE status :(")
            return False


        # voltage = (response[0x09] * 256) + response[0x08]
        #bb0200690f000000b7140000000000000000
        #bb0200df050000005f000000000000000000
        # return voltage

    def getBattery(self):
        cmd = bytearray(0x12)
        cmd[0x00] = 0xee
        cmd[0x01] = 0x02
        #cmd[0x03] = 0x0c #checksum?
        cmd[0x04] = 0x05 #battery %
        #cmd[0x04] = 0x0F #batteryVoltage
        #cmd[0x10] = 0x02
        if self.session is None:
            raise Exception("Session is None! getVoltage failed.")
        response = self.session.execute(cmd)
        battery = response[0x08]

        return battery

    def disconnect(self):
        try:
            self.conn_state = "disconnected"



            if self.session is not None:
                if self.session.notificationProcessor is not None:
                    self.session.notificationProcessor.stop()
                    self.session.notificationProcessor.should_abort_immediately = True 
            self.is_secure = False
            self.session = None
            if self.peripheral is not None:
                self.peripheral.disconnect() #should probably put this line in a try/except
                self.peripheral = None
            logging.info('Disconnected cleanly...')
        except Exception as e:
            logging.error(f"An error occurred during disconnect: {e}")
        return True

    def led_G(self):
        cmd = self.session.build_command(14)
        cmd[4] = 0x01
        response = self.session.execute(cmd)

    def led_R(self):
        cmd = self.session.build_command(14)
        cmd[4] = 0x00
        response = self.session.execute(cmd)

    def is_connected(self):
        return type(self.session) is session.Session \
            and self.is_secure and self.conn_state == "connected"

        #return type(self.session) is session.Session \
        #    and self.peripheral.addr is not None
