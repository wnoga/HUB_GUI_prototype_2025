import asyncio
import numpy as np
import socket
import threading
import time
import queue


class HubInterface:
    """
    A class for managing a connection to a hub over a network socket.
    """

    def __init__(self, ip="192.168.1.100", port=5555, loop=None):
        """
        Initializes the HubInterface with default values.
        """
        self.ip = ip
        self.port = port
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self.connected = False
        self.timeout_s = 30  # General timeout for operations
        self._loop = loop if loop else asyncio.get_event_loop()

    async def connect(self):
        """
        Establishes a connection to the hub at the specified IP and port.
        """
        if self.connected:
            await self.disconnect()

        self.connected = False
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=self.timeout_s
            )
            self.connected = True
        except asyncio.TimeoutError:
            print(f"Connection to {self.ip}:{self.port} timed out.")
        except ConnectionRefusedError:
            print(f"Connection to {self.ip}:{self.port} refused.")
        except Exception as e:
            print(f"Error connecting to {self.ip}:{self.port}: {e}")

    async def disconnect(self):
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                print(f"Error closing writer: {e}")
        self.reader = None
        self.writer = None
        self.connected = False

    async def send(self, data_str: str, waitForResponseData=True):
        """
        Sends data to the connected hub and receives a response.

        Args:
            data_str (str): The data to send.
            waitForResponseData (bool): Whether to wait for and receive response data.

        Returns:
            dict or None: The received JSON data as a dictionary, or None if an error occurred.
        """
        print(f"Try send: {data_str}")
        try:
            if not self.connected:
                await self.connect()
            
            if not self.connected:
                return {"status": "ERROR", "message": "Not connected"}

            self.writer.write(f"{data_str}\r\n".encode())
            await self.writer.drain()

            response_data = None
            if waitForResponseData:
                response_data = await self.receive()

            await self.disconnect()
            return {"status": "OK", "data": response_data}
        except asyncio.TimeoutError:
            print(f"Timeout sending/receiving data for: {data_str}")
            await self.disconnect()
            return {"status": "ERROR", "message": "Operation timed out"}
        except Exception as e:
            print(f"Error sending data: {e}")
            await self.disconnect()
            return {"status": "ERROR", "message": str(e)}

    async def receive(self):
        if not self.connected or not self.reader:
            return None
            
        buffer = bytearray()
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        try:
            while True:
                remaining_time = self.timeout_s - (loop.time() - start_time)
                if remaining_time <= 0:
                    print(f"Receive timeout with partial data: {buffer.decode(errors='ignore')[:100]}" if buffer else "Receive timeout, no data.")
                    return buffer.decode(errors='ignore') if buffer else None

                try:
                    chunk_timeout = min(2.0, remaining_time) # Read attempt timeout
                    chunk = await asyncio.wait_for(self.reader.read(1024), timeout=chunk_timeout)
                    
                    if not chunk: # EOF
                        self.connected = False
                        return buffer.decode(errors='ignore') if buffer else None
                    
                    buffer.extend(chunk)
                    try:
                        decoded_data = buffer.decode()
                        json.loads(decoded_data) # Check if valid JSON
                        return decoded_data
                    except UnicodeDecodeError: # Incomplete multi-byte char
                        if (loop.time() - start_time) >= self.timeout_s: return None
                    except json.JSONDecodeError: # Valid UTF-8, but not JSON yet
                        if (loop.time() - start_time) >= self.timeout_s:
                            print(f"Receive timeout, incomplete JSON: {buffer.decode(errors='ignore')[:100]}")
                            return buffer.decode(errors='ignore') # Return what we have
                except asyncio.TimeoutError: # Timeout for a chunk
                    pass # Outer loop checks overall timeout
        except ConnectionResetError:
            print("Connection reset by peer during receive.")
            self.connected = False
            return buffer.decode(errors='ignore') if buffer else None
        except Exception as e:
            print(f"Error during receive: {e}")
            self.connected = False
            return buffer.decode(errors='ignore') if buffer else None
        
        # Fallback, should ideally be handled by timeout logic above
        if buffer:
            return buffer.decode(errors='ignore')
        else:
            return None

class AFE:
    """
    A class representing an AFE (Analog Front-End) device.
    Could be used to store configuration or state specific to an AFE.
    """
    def __init__(self, afe_id):
        self.afe_id = afe_id
        self.config = {} # To store configuration data
        self.measurements = {} # To store measurement data
    
    def add_measurement(self, data_json):
        # if self.measurements.get(measurement_name) is None:
        #     self.measurements[measurement_name] = pd.DataFrame({"time":[],"value":[]})
        # # self.measurements[measurement_name]
        # print(self.afe_id, measurement_name, data)
        # print(data_json)
        if self.measurements.get("last_data") is None:
            self.measurements["last_data"] = pd.DataFrame()
        retval = data_json.get("retval", None)
        if retval is None or not isinstance(retval, dict):
            return
        
        last_data = retval.get("last_data")
        if last_data is not None:
            # Convert last_data (which is a dict) to a DataFrame and append/update
            new_df = pd.DataFrame([last_data])
            new_df["gui_timestamp"] = time.time()
            new_df["gui_datetime"] = pd.to_datetime(new_df["gui_timestamp"], unit='s')
            self.measurements["last_data"] = pd.concat([self.measurements["last_data"], new_df], ignore_index=True)
            # self.measurements.update("last_data", new_df)
            # print(self.measurements[""])
        # for k in self.measurements.keys():
        #     print(k, self.measurements[k])

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

class MainScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)

        self.ip_input = TextInput(text='192.168.1.100', multiline=False)
        self.add_widget(Label(text='Enter HUB IP:'))
        self.add_widget(self.ip_input)

        self.port_input = TextInput(text='5555', multiline=False)
        self.add_widget(Label(text='Enter Port:'))
        self.add_widget(self.port_input)

        self.send_button = Button(text='Send Command')
        self.send_button.bind(on_press=self.send_command)
        self.add_widget(self.send_button)

        self.response_label = Label(text="Response:")
        self.add_widget(self.response_label)

    def send_command(self, instance):
        ip = self.ip_input.text
        port = self.port_input.text
        print(f"Sending to {ip}:{port}")
        self.response_label.text = f"Sent to {ip}:{port}"
    def parse_response(self, command_json, response_data_json):
        """
        Handles parsing of data based on the command and updates internal state.
        """
        procedure = command_json.get("procedure")
        afe_id = str(command_json.get("afe_id", ""))

        if procedure == "get_all_afe_configuration":
            for k, v in response_data_json.items():
                if k not in self.afe:
                    self.afe[k] = AFE(k)
                self.afe[k].config = v
            self.afe_id_new_list = sorted(self.afe.keys())

        elif procedure == "default_get_measurement_last":
            afe = self.afe.get(afe_id)
            if afe is None:
                print(f"No AFE object found for ID {afe_id}")
                return
            afe.add_measurement(response_data_json)
            self.plot_data_changed = True

        elif procedure == "afe_set_sipm_voltage_si":
            print(f"Voltage set response for AFE {afe_id}: {response_data_json}")

        else:
            print(f"No specific parser logic for procedure: {procedure}")


class HubApp(App):
    def build(self):
        return MainScreen()

if __name__ == '__main__':
    HubApp().run()
