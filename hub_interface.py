import asyncio
import numpy as np
import socket
import threading
import time
import queue
import tkinter as tk
import json
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import argparse
import seaborn as sns
import datetime

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

        

class App:
    def __init__(self, master: tk.Tk, ip="192.168.1.100", port=5555):
        self.master = master
        master.title("HUB Interface")
        self.app_running = True
        
        self.afe = {} # List of AFE objects
        
        # Asyncio loop setup
        self.aio_loop = asyncio.new_event_loop()
        self.aio_thread = threading.Thread(target=self._run_aio_loop, daemon=True)
        self.aio_thread.start()

        self.ip = None
        # self.hub = None # HubInterface instances created on demand

        self.port = None


        self.response_text_queue = queue.Queue()

        self.afe_id_new_list = None
        self.afe_id = None
        self.afe_id_all = []

        self.plot_data_changed = False # Flag to indicate if new data is available for plotting
        self.plot_main_frame = None # Frame to hold matplotlib canvases

        self.data_to_plot = {} # Key: device_id, Value: {measurement_name: DataFrame}

        self.label = tk.Label(master, text="Enter HUB IP:")
        self.label.pack()

        self.ip_frame = tk.Frame(master)
        self.ip_frame.pack()

        self.ip_entry = tk.Entry(self.ip_frame)
        self.ip_entry.pack()
        self.port_entry = tk.Entry(self.ip_frame)
        self.port_entry.pack(side=tk.RIGHT)
        self.port_entry.insert(0, port)
        self.ip_entry.insert(0, ip)
        # Bind the <Return> key to change_ip
        self.ip_entry.bind("<Return>", self.change_ip_and_port)
        self.port_entry.bind("<Return>", self.change_ip_and_port)

        # Automatic data acquisition
        self.auto_get_data_frame = tk.Frame(master)
        self.auto_get_data_frame.pack()

        self.auto_get_data_var = tk.StringVar(master)
        self.auto_get_data_var.set("Disabled") # Default value
        self.auto_get_data_options = ["Disabled", "5 s", "10 s", "60 s"]
        self.auto_get_data_dropdown = tk.OptionMenu(self.auto_get_data_frame, self.auto_get_data_var, *self.auto_get_data_options)
        self.auto_get_data_dropdown.pack(side=tk.LEFT)
        # Call start_auto_get_data whenever the selection changes
        self.auto_get_data_var.trace_add("write", self.start_auto_get_data)


        self.auto_get_data_label = tk.Label(self.auto_get_data_frame, text="Automatic Get Data All AFEs:")
        self.auto_get_data_label.pack(side=tk.LEFT)

        self.send_label = tk.Label(master, text="Enter JSON command:")
        self.send_label.pack()

        self.command_entry = tk.Entry(master)
        self.command_entry.pack()

        self.afe_id_label = tk.Label(master, text="Select AFE ID:")
        self.afe_id_label.pack()

        self.afe_id_var = tk.StringVar(master)
        self.afe_id_dropdown = tk.OptionMenu(master, self.afe_id_var, None)
        self.afe_id_dropdown.pack()
        # Bind the trace to update self.afe_id when the dropdown selection changes. This is done in the update_gui function now
        # self.afe_id_var.trace_add("write", self.update_selected_afe_id)

        self.send_button = tk.Button(
            master, text="Send Command", command=self.send_command)
        self.send_button.pack()

        # Add buttons for specific commands
        self.buttons_frame = tk.Frame(master)
        self.buttons_frame.pack()

        self.get_config_button = tk.Button(
            self.buttons_frame, text="Get Config", command=lambda: self.send_predefined_command({"procedure": "get_all_afe_configuration"}))
        self.get_config_button.pack(side=tk.LEFT)

        self.get_measurement_button = tk.Button(
            self.buttons_frame, text="Get Measurement", command=lambda: self.send_predefined_command({"afe_id": int(self.afe_id_var.get()), "procedure": "default_get_measurement_last"}))
        self.get_measurement_button.pack(side=tk.LEFT)

        self.default_procedure_button = tk.Button(
            self.buttons_frame, text="Default Procedure", command=lambda: self.send_predefined_command({"afe_id": int(self.afe_id_var.get()), "procedure": "default_procedure"}))
        self.default_procedure_button.pack(side=tk.LEFT)

        self.set_dac_button = tk.Button(
            self.buttons_frame, text="Set DAC", command=lambda: self.send_predefined_command({"afe_id": int(self.afe_id_var.get()), "procedure": "default_set_dac"}))
        self.set_dac_button.pack(side=tk.LEFT)

        self.hv_on_button = tk.Button(
            self.buttons_frame, text="HV On", command=lambda: self.send_predefined_command({"afe_id": int(self.afe_id_var.get()), "procedure": "default_hv_set", "enable": True}))
        self.hv_on_button.pack(side=tk.LEFT)

        self.get_all_data_button = tk.Button(
            self.buttons_frame, text="Get Data All AFEs", command=self.get_data_for_all_afes)
        self.get_all_data_button.pack(side=tk.LEFT)

        self.show_settings_button = tk.Button(
            self.buttons_frame, text="Show Settings", command=self.show_settings_popup_by_id)
        self.show_settings_button.pack(side=tk.LEFT)
        
        
        self.show_settings_button = tk.Button(
            self.buttons_frame, text="Get status", command=lambda: self.send_predefined_command({"afe_id": int(self.afe_id_var.get()), "procedure": "afe_get_subdevice_status", "subdevice_mask": 0x03}))
        self.show_settings_button.pack(side=tk.LEFT)


        # Add controls for setting HV voltage
        self.hv_set_frame = tk.Frame(master)
        self.hv_set_frame.pack()

        self.hv_set_label = tk.Label(self.hv_set_frame, text="Set HV Voltage (V):")
        self.hv_set_label.pack(side=tk.LEFT)

        self.hv_voltage_entry = tk.Entry(self.hv_set_frame, width=10)
        self.hv_voltage_entry.insert(0, "0") # Default value
        self.hv_voltage_entry.pack(side=tk.LEFT)

        # Add option menu for HV control mode (master/slave/both)
        self.hv_mode_var = tk.StringVar(master)
        self.hv_mode_var.set("Both") # Default value
        self.hv_mode_options = {
            "Master": 0x01,
            "Slave": 0x02,
            "Both": 0x03
        }
        self.hv_mode_dropdown = tk.OptionMenu(self.hv_set_frame, self.hv_mode_var, *self.hv_mode_options.keys())
        self.hv_mode_dropdown.pack(side=tk.LEFT)

        self.set_hv_button = tk.Button(
            self.hv_set_frame, text="Set HV",
            command=self.set_hv_voltage)
        self.set_hv_button.pack(side=tk.LEFT)
        
        

        self.response_label = tk.Label(master, text="Response:")
        self.response_label.pack()
        self.response_text = tk.Text(master, height=10, width=50)
        self.response_text.pack()
        self.response_text.see(tk.END)  # Auto-scroll to the end

        # Add a button to open the plot window
        self.plot_button = tk.Button(
            master, text="Open Plot Window", command=self.open_plot_window)
        self.plot_button.pack()
        self.plot_window = None
        
        # Initialize ip and port from entries, then create HubInterface
        self.change_ip_and_port()

        self.auto_get_data_future = None # To store the asyncio future for auto data fetching

    def _run_aio_loop(self):
        asyncio.set_event_loop(self.aio_loop)
        try:
            self.aio_loop.run_forever()
        finally:
            # Clean up any tasks that might be pending if loop is stopped abruptly
            # For tasks like auto_get_data_future, cancellation should be handled in quit()
            self.aio_loop.close()

    def quit(self):
        print("quittt")
        self.app_running = False # Stop the update_gui loop
        self.stop_auto_get_data() # Stop the automatic data fetching task

        if self.aio_loop.is_running():
            self.aio_loop.call_soon_threadsafe(self.aio_loop.stop)
        # self.aio_thread.join(timeout=2) # Wait for the asyncio thread to finish

    def send_command(self):
        command_str = self.command_entry.get()
        try:
            command_json = json.loads(command_str)
            asyncio.run_coroutine_threadsafe(
                self.async_handle_command(command_json),
                self.aio_loop
            )
        except json.JSONDecodeError:
            self.response_text_queue.put((tk.END, "Invalid JSON format\n"))
        except Exception as e:
            self.response_text_queue.put((tk.END, f"Error preparing to send command: {e}\n"))

    def change_ip_and_port(self, event=None):
        """Changes the HUB IP address."""
        new_ip = self.ip_entry.get()
        new_port = int(self.port_entry.get())

        self.ip = new_ip
        self.port = new_port
        
        # HubInterface instances are created on-demand in async_handle_command
        # using self.ip and self.port. So, this change will take effect for subsequent commands.
        self.response_text_queue.put(
            (tk.END, f"HUB IP changed to {new_ip}:{new_port}. New commands will use this address.\n"))

    def isThisCommandReturnData(self, command):
        # Add procedures that are expected to return data here
        data_returning_commands = [
            "get_all_afe_configuration",
            "default_get_measurement_last",
            "default_procedure",
            "default_set_dac",
            "default_hv_set",
            "default_hv_off",
            "default_cal_in_set",
            "get_data"
            # Add other procedures that return data
        ]
        return command in data_returning_commands

    async def async_handle_command(self, command_json):
        # Create a new HubInterface instance for each command.
        # This matches original threading logic and avoids shared state issues.
        hub = HubInterface(ip=self.ip, port=self.port, loop=self.aio_loop)
        command_str = json.dumps(command_json)
        try:
            response = await hub.send(
                command_str, waitForResponseData=self.isThisCommandReturnData(command_json.get("procedure"))
            )
            gui_timestamp = time.time()
            self.response_text_queue.put(
                (tk.END, f"{datetime.datetime.utcnow()} @ Sent: {command_str} -> {response.get("status", "ERROR")}\n"))
            self.response_text_queue.put(
                (tk.END, f"{datetime.datetime.utcnow()} @ Recieved: {command_str} -> {response}\n"))
            
            procedure = command_json.get("procedure", None)
            # print(f"Procedure: {procedure} -> {response}")
            if response.get("status") == "OK" and response.get("data"):
                response_data_str = response["data"]
                try:
                    response_data_json = json.loads(response_data_str)
                    if procedure == "get_all_afe_configuration":
                        # print(response_data_json)
                        for k in response_data_json.keys():
                            if k not in self.afe:
                                self.afe[k] = AFE(k)
                                self.afe[k].config = response_data_json[k]
                        afe_id_all = self.afe_id_all
                        self.afe_id_all = list(self.afe.keys())
                        if self.afe_id_all != afe_id_all:
                            self.afe_id_new_list = self.afe_id_all
                        # for afe in self.afe.values():
                        #     print(afe.config)
                    
                    elif procedure == "default_get_measurement_last":
                        device_id = response_data_json.get("device_id", None)
                        # print(device_id, "default_get_measurement_last")
                        afe = self.afe.get(str(device_id), None)
                        if afe is None:
                            print("No afe found: ", device_id)
                            return
                        #     self.afe.update({device_id: AFE(device_id)})
                        #     afe = self.afe[device_id]
                        # afe = self.afe.get(device_id, None)
                        # print(afe_id)
                        afe.add_measurement(response_data_json)
                        self.plot_data_changed = True
                            


                    # elif procedure == "default_get_measurement_last":
                    #     device_id = response_data_json.get("device_id", None)
                    #     afe = self.afe.get(device_id, None)
                    #     if afe is None:
                    #         self.afe.update({device_id: AFE(device_id)})
                    #         afe = self.afe.get(device_id, None)
                        
                        # print(response_data_json)
                        
                        # toAppend = response_data_json.get("retval", None)
                        # if toAppend and isinstance(toAppend, dict):
                        #     for k, v_measurement_dict in toAppend.items():
                        #         if not isinstance(v_measurement_dict, dict):
                        #             # self.response_text_queue.put((tk.END, f"Warning: Expected dict for measurement {k}, got {type(v_measurement_dict)}"))
                        #             print(f"Warning: Expected dict for measurement {k}, got {type(v_measurement_dict)}")
                        #             continue
                                
                        #         v_measurement_dict["device_id"] = device_id
                        #         v_measurement_dict["gui_timestamp"] = gui_timestamp
                        #         v_measurement_dict["gui_datetime"] = pd.to_datetime(v_measurement_dict["gui_timestamp"], unit='s')

                        #         # Store raw measurement data in AFE object
                        #         if k not in self.afe[device_id].measurements:
                        #             self.afe[device_id].measurements[k] = []
                        #         self.afe[device_id].measurements[k].append(v_measurement_dict)

                        #         df = pd.DataFrame([v_measurement_dict])

                        #         if k in self.data_to_plot[device_id]:
                        #             self.data_to_plot[device_id][k] = pd.concat(
                        #                 [self.data_to_plot[device_id][k], df], ignore_index=True
                        #             )
                        #         elif k == 'config': # Handle config data separately
                        #                 config_data = v_measurement_dict # This is the dict, not a DataFrame
                        #                 if config_data:
                        #                     self.master.after(0, lambda: self.show_settings_popup(config_data))
                        #                 else:
                        #                     self.response_text_queue.put((tk.END, f"Warning: Empty config data received for device {device_id}.\n"))

                        #                 # Since 'config' is not a measurement, don't store it as one
                        #                 continue
                        #         else: # First time seeing this measurement type
                        #             # If not 'config', proceed to store the measurement
                        #             # This branch is for initial DataFrame creation

                        #             self.data_to_plot[device_id][k] = df
                                
                        #         self.data_to_plot[device_id][k].sort_values(by="gui_timestamp", inplace=True)
                        #     self.plot_data_changed = True
                        
                        # if device_id and device_id in self.afe: # Ensure device_id is valid and AFE object exists
                        #     if device_id not in self.data_to_plot:
                        #         self.data_to_plot[device_id] = {}
                            
                            
                        #     toAppend = response_data_json.get("retval", None)
                        #     if toAppend and isinstance(toAppend, dict):
                        #         for k, v_measurement_dict in toAppend.items():
                        #             if not isinstance(v_measurement_dict, dict):
                        #                 # self.response_text_queue.put((tk.END, f"Warning: Expected dict for measurement {k}, got {type(v_measurement_dict)}"))
                        #                 print(f"Warning: Expected dict for measurement {k}, got {type(v_measurement_dict)}")
                        #                 continue
                                    
                        #             v_measurement_dict["device_id"] = device_id
                        #             v_measurement_dict["gui_timestamp"] = gui_timestamp
                        #             v_measurement_dict["gui_datetime"] = pd.to_datetime(v_measurement_dict["gui_timestamp"], unit='s')

                        #             # Store raw measurement data in AFE object
                        #             if k not in self.afe[device_id].measurements:
                        #                 self.afe[device_id].measurements[k] = []
                        #             self.afe[device_id].measurements[k].append(v_measurement_dict)

                        #             df = pd.DataFrame([v_measurement_dict])

                        #             if k in self.data_to_plot[device_id]:
                        #                 self.data_to_plot[device_id][k] = pd.concat(
                        #                     [self.data_to_plot[device_id][k], df], ignore_index=True
                        #                 )
                        #             elif k == 'config': # Handle config data separately
                        #                     config_data = v_measurement_dict # This is the dict, not a DataFrame
                        #                     if config_data:
                        #                         self.master.after(0, lambda: self.show_settings_popup(config_data))
                        #                     else:
                        #                         self.response_text_queue.put((tk.END, f"Warning: Empty config data received for device {device_id}.\n"))

                        #                     # Since 'config' is not a measurement, don't store it as one
                        #                     continue
                        #             else: # First time seeing this measurement type
                        #                 # If not 'config', proceed to store the measurement
                        #                 # This branch is for initial DataFrame creation

                        #                 self.data_to_plot[device_id][k] = df
                                    
                        #             self.data_to_plot[device_id][k].sort_values(by="gui_timestamp", inplace=True)
                        #         self.plot_data_changed = True
                                
                    # Other procedures that return data can be handled here similarly.
                    # The original code had specific self.hub.receive() calls for some procedures after send.
                    # This is now handled by HubInterface.send(waitForResponseData=True).
                    # If a procedure has a more complex multi-stage response, HubInterface or this handler would need adjustment.

                except json.JSONDecodeError as e:
                    self.response_text_queue.put((tk.END, f"Error decoding JSON response for {command_str} [{response_data_str}]: {e}\nData: {response_data_str[:200]}\n"))
                except TypeError: # If response["data"] is None or not string
                    self.response_text_queue.put((tk.END, f"No data or invalid data type in response for {command_str}\n"))
            elif response.get("status") == "ERROR":
                 self.response_text_queue.put((tk.END, f"HUB Error for {command_str}: {response.get('message')}\n"))
                 
        except Exception as e:
            self.response_text_queue.put(
                (tk.END, f"Error in async_handle_command for {command_str}: {e}\n"))

    def open_plot_window(self):
        """Opens a new window for plotting data."""
        if not self.plot_window or not tk.Toplevel.winfo_exists(self.plot_window):
            self.plot_window = tk.Toplevel(self.master)
            self.plot_window.title("AFE Data Plot")
            self.plot_window.geometry("600x400")
            
            # Create a frame to hold the matplotlib canvases
            self.plot_main_frame = tk.Frame(self.plot_window)
            self.plot_main_frame.pack(fill=tk.BOTH, expand=True)
            
            self.plot_data_changed = True # Ensure plot is drawn when window opens
        else:
            self.plot_window.lift()  # Bring the window to the front

    def plot(self):
        """Plots data in the plot window."""
        # Ensure the plot window and its main frame exist
        if not self.plot_window or not tk.Toplevel.winfo_exists(self.plot_window) or not hasattr(self, 'plot_main_frame') or not self.plot_main_frame:
             return # Cannot plot if window/frame not ready

        # Clear previous plots by destroying all widgets in the main plot frame
        for widget in self.plot_main_frame.winfo_children():
            widget.destroy()
        
        toPlot = []
        for afe in self.afe.values():
            toAppend = afe.measurements.get("last_data", None)
            if toAppend is not None:
                toAppend["device_id"] = afe.afe_id
                toPlot.append(toAppend)
        # print(toPlot)
        toPlot = pd.concat(toPlot,ignore_index=True)
        toPlot.sort_values(by="gui_timestamp", inplace=True)
        columns_to_plot = [
            'U_SIPM_MEAS0', 'U_SIPM_MEAS1',
            'I_SIPM_MEAS0', 'I_SIPM_MEAS1',
            'TEMP_EXT', 'TEMP_LOCAL'
        ]
        
        column_name_base = {
            "TEMP": 0,
            "U_SIPM": 1, 
            "I_SIPM": 2
        }

        figures_created = []
        fig, axes = plt.subplots(3, 1, sharex=True, figsize=(7, 8))
        figures_created.append(fig)
        time_column = "gui_timestamp"

        # Loop through each group of columns
        for col_name, ax_idx in column_name_base.items():
            m = "LOCAL" if col_name == "TEMP" else "MEAS0"
            s = "EXT" if col_name == "TEMP" else "MEAS1"

            m_col = f"{col_name}_{m}"
            s_col = f"{col_name}_{s}"

            if m_col in toPlot.columns and s_col in toPlot.columns:
                # Melt the dataframe to long-form
                melted = pd.melt(
                    toPlot,
                    id_vars=["gui_timestamp", "device_id"],
                    value_vars=[m_col, s_col],
                    var_name="measurement_type",
                    value_name="value"
                )

                # Plot using measurement_type for style (e.g., MEAS0 vs MEAS1)
                sns.lineplot(
                    data=melted,
                    x="gui_timestamp",
                    y="value",
                    hue="device_id",
                    style="measurement_type",
                    markers=True,
                    dashes={
                        m_col: "",    # solid for MEAS0/LOCAL
                        s_col: (2, 2) # dashed for MEAS1/EXT
                    },
                    ax=axes[ax_idx]
                )
        # Customize plot appearance and labels
        axes[0].set_ylabel(r"TEMP [°C]")
        axes[1].set_ylabel(r"U SiPM [V]")
        axes[2].set_ylabel(r"I SiPM [A]")

        for ax in axes:
            if ax.has_data():
                ax.legend(loc='upper left', fontsize='x-small')
            ax.tick_params(axis='x', labelsize=7)
            ax.grid(True, linestyle=':', alpha=0.7)

        fig.tight_layout(rect=[0, 0.03, 1, 0.95])

        # Embed plot in Tkinter frame
        canvas_agg = FigureCanvasTkAgg(fig, master=self.plot_main_frame)
        canvas_agg.draw()
        canvas_agg.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        plt.close(fig)

    async def _auto_get_data_loop(self, interval_seconds):
        """Asyncio task for periodically fetching data."""
        try:
            while self.app_running: # Check app_running as well
                if self.auto_get_data_var.get() == "Disabled":
                    break # Exit if disabled
                
                print(f"Auto-fetching data for all AFEs (interval: {interval_seconds}s)")
                if self.afe_id_all:
                    for afe_id_str in self.afe_id_all:
                        try:
                            # Sequentially await each command to avoid overwhelming.
                            # Could be done concurrently with asyncio.gather if hub supports it well.
                            await self.async_handle_command({
                                "afe_id": int(afe_id_str), 
                                "procedure": "default_get_measurement_last"
                            })
                        except ValueError:
                            self.response_text_queue.put((tk.END, f"Invalid AFE ID for auto 'Get Data All': {afe_id_str}\n"))
                        except Exception as e:
                            self.response_text_queue.put((tk.END, f"Error auto-fetching for AFE {afe_id_str}: {e}\n"))
                else:
                    self.response_text_queue.put((tk.END, "Auto-fetch: No AFE IDs known. Press 'Get Config' first.\n"))
                
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            print("Auto-get data loop cancelled.")
        except Exception as e:
            print(f"Error in auto_get_data_loop: {e}")
            self.response_text_queue.put((tk.END, f"Critical error in auto_get_data_loop: {e}\n"))

    def start_auto_get_data(self, *args): # Accept *args for trace compatibility
        """
        Manages the automatic data fetching process based on the dropdown selection.
        """
        if hasattr(self, 'auto_get_data_future') and self.auto_get_data_future:
            if not self.auto_get_data_future.done():
                self.auto_get_data_future.cancel()
            self.auto_get_data_future = None

        selected_option = self.auto_get_data_var.get()
        print(f"Auto Get Data: Selection changed to '{selected_option}' or timer fired.")

        if selected_option == "Disabled":
            return

        # Extract seconds from the option string (e.g., "5 s" -> 5)
        try:
            seconds_str = selected_option.split(" ")[0]
            interval_s = int(seconds_str)
            if interval_s <= 0:
                print("Auto-fetch interval must be positive.")
                return
        except (ValueError, IndexError):
            print(f"Error parsing interval from '{selected_option}'. Stopping auto-fetch.")
            return

        # Schedule the asyncio task
        self.auto_get_data_future = asyncio.run_coroutine_threadsafe(
            self._auto_get_data_loop(interval_s),
            self.aio_loop
        )
        print(f"Scheduled auto data fetch every {interval_s} s.")

    def stop_auto_get_data(self):
        """Stops the automatic data fetching process."""
        if hasattr(self, 'auto_get_data_future') and self.auto_get_data_future:
            if not self.auto_get_data_future.done():
                self.auto_get_data_future.cancel()
            self.auto_get_data_future = None
            print("Auto data fetching stopped.")

    def send_predefined_command(self, command_json):
        asyncio.run_coroutine_threadsafe(
            self.async_handle_command(command_json), 
            self.aio_loop
        )

    def get_data_for_all_afes(self):
        """Sends 'default_get_measurement_last' to all known AFE IDs."""
        if self.afe_id_all:
            for afe_id_str in self.afe_id_all:
                try:
                    command_json = {"afe_id": int(afe_id_str), "procedure": "default_get_measurement_last"}
                    asyncio.run_coroutine_threadsafe( # Schedule each one
                        self.async_handle_command(command_json), self.aio_loop
                    )
                except ValueError:
                    self.response_text_queue.put((tk.END, f"Invalid AFE ID for 'Get Data All': {afe_id_str}\n"))
        else:
            self.response_text_queue.put((tk.END, "No AFE IDs known. Press 'Get Config' first.\n")) 


    def show_settings_popup_by_id(self):
        if not self.afe_id:
            self.response_text_queue.put((tk.END, "Select an AFE ID first.\n"))
            return

        afe = self.afe.get(str(self.afe_id), None)
        # if afe_id not in self.data_to_plot or "config" not in self.data_to_plot[afe_id]:
        #     self.response_text_queue.put((tk.END, f"No settings data available for AFE ID {afe_id}.\n"))
        #     return

        # settings_data = self.data_to_plot[afe_id]["config"].iloc[-1].to_dict() # Get the last config data
        settings_data = afe.config
        self.show_settings_popup(settings_data)

    def show_settings_popup(self, settings_data):
        
        """Displays a popup window with AFE settings, handling missing sections."""
        popup = tk.Toplevel(self.master)
        popup.title(f"AFE Settings (ID: {settings_data.get('ID', 'N/A')})")

        settings = settings_data

        master_settings = settings.get("M", {})
        slave_settings = settings.get("S", {})

        if not master_settings and not slave_settings:
            tk.Label(popup, text="No settings data available.").pack(pady=10)
            return  # Exit if no settings are found

        # Get all unique keys from both master and slave settings
        all_keys = sorted(list(set(master_settings.keys()) | set(slave_settings.keys())))

        # Create a frame for the table-like layout
        table_frame = tk.Frame(popup)
        table_frame.pack(padx=10, pady=10)

        # Header row
        tk.Label(table_frame, text="Setting", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=5, pady=2, sticky="w")
        tk.Label(table_frame, text="Master (M)", font=("Arial", 10, "bold")).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        tk.Label(table_frame, text="Slave (S)", font=("Arial", 10, "bold")).grid(row=0, column=2, padx=5, pady=2, sticky="w")

        # Data rows
        for i, key in enumerate(all_keys):
            row_num = i + 1
            tk.Label(table_frame, text=key, font=("Arial", 9)).grid(row=row_num, column=0, padx=5, pady=1, sticky="w")

            master_value = master_settings.get(key, "N/A")
            slave_value = slave_settings.get(key, "N/A")

            tk.Label(table_frame, text=str(master_value), font=("Arial", 9)).grid(row=row_num, column=1, padx=5, pady=1, sticky="w")
            tk.Label(table_frame, text=str(slave_value), font=("Arial", 9)).grid(row=row_num, column=2, padx=5, pady=1, sticky="w")

        # # Use .get() with default {} to safely access nested dicts, handling missing 'M' or 'S'
        # if "M" in settings and "S" in settings:  # Both Master and Slave settings are present
        #     setting_groups = {"Master (M)": settings["M"], "Slave (S)": settings["S"]}
        # elif "M" in settings:
        #     setting_groups = {"Master (M)": settings["M"]}
        # elif "S" in settings:
        #     setting_groups = {"Slave (S)": settings["S"]}
        # else:
        #     tk.Label(popup, text="No settings data available.").pack(pady=10)
        #     return  # Exit if no settings are found

        # for group_name, group_settings in setting_groups.items():
        #     tk.Label(popup, text=group_name, font=("Arial", 12, "bold")).pack(pady=5)
        #     for key, value in group_settings.items():
        #         setting_str = f"{key}: {value}"
        #         setting_label = tk.Label(popup, text=setting_str)
        #         setting_label.pack(anchor="w", padx=10, pady=2)

        close_button = tk.Button(popup, text="Close", command=popup.destroy)
        close_button.pack(pady=10)

    def set_hv_voltage(self):
        """Sends a command to set the HV voltage for the selected AFE."""
        try:
            print("Set HV Voltage - AFE_ID", self.afe_id_var.get())
            afe_id = int(self.afe_id_var.get())
            voltage = float(self.hv_voltage_entry.get())
            mode = self.hv_mode_options.get(self.hv_mode_var.get())
            command_json = {
                "afe_id": afe_id,
                "procedure": "afe_set_sipm_voltage_si",
                "voltage": voltage,
                "afe_subdevice": mode
            }
            print("command_json", command_json)
            self.send_predefined_command(command_json)
        except ValueError:
            self.response_text_queue.put((tk.END, "Invalid AFE ID or Voltage value.\n"))
        except Exception as e:
            self.response_text_queue.put((tk.END, f"Error setting HV voltage: {e}\n"))
    def update_selected_afe_id(self, *args):
        """Updates the self.afe_id attribute when the dropdown selection changes."""
        self.afe_id = self.afe_id_var.get()
        print(f"Selected AFE ID: {self.afe_id}")

    def update_gui(self):
        """
        Polls the response_text_queue for messages and updates the GUI's text widget.
        Also checks for new AFE ID lists and updates the AFE dropdown.
        Schedules the next update.
        """
        # Print to log view
        while not self.response_text_queue.empty():
            message = self.response_text_queue.get()
            self.response_text.insert(*message)
            self.response_text.see(tk.END)  # Auto-scroll to the end

        # Update list of AFES
        if self.afe_id_new_list:
            # Sort IDs for consistent order in dropdown, e.g., numerically
            try:
                self.afe_id_new_list = sorted(self.afe_id_new_list, key=int)
            except ValueError:  # Handle non-integer IDs if they can occur
                self.afe_id_new_list = sorted(self.afe_id_new_list)

            # Set default selection
            self.afe_id_var.set(self.afe_id_new_list[0])
            self.update_selected_afe_id()  # Update self.afe_id after setting the default
            menu = self.afe_id_dropdown["menu"]
            menu.delete(0, "end")  # Clear previous items
            self.afe_id_all = self.afe_id_new_list.copy()
            for afe_id_str in self.afe_id_new_list:
                menu.add_command(label=afe_id_str, command=tk._setit(
                    self.afe_id_var, afe_id_str))
            self.afe_id_new_list = None  # Clear the new list after processing
        # else:
        #     self.afe_id_var.set("N/A")  # No AFEs found
        #     menu = self.afe_id_dropdown["menu"]
        #     menu.delete(0, "end")
            self.afe_id_new_list = None  # Clear the new list after processing

        # Plot data
        # print("plot_data_changed", self.plot_data_changed)
        if self.plot_data_changed:
            if self.plot_window and tk.Toplevel.winfo_exists(self.plot_window): # Only plot if window is open
                self.plot()
            self.plot_data_changed = False # Reset flag after plotting attempt
        if self.app_running: # Continue polling only if app is running and not closing
            self.master.after(100, self.update_gui)  # Poll every 100ms


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HUB GUI Interface")
    parser.add_argument("--ip", type=str, default="10.42.0.92", help="HUB IP address")
    parser.add_argument("--port", type=int, default=5555, help="HUB port number")
    args = parser.parse_args()

    root = tk.Tk()
    gui = App(root, ip=args.ip, port=args.port)

    def handle_closing():
        print("CLOSING APP")
        gui.quit() # This now sets app_running to False, stops auto_get_data, and signals asyncio loop to stop
        root.destroy()

    # SIGINT (Ctrl+C) is usually handled by Tkinter's mainloop or can be
    # more complex with threads. For GUI apps, WM_DELETE_WINDOW is primary.
    # If running from a terminal where Ctrl+C is expected to quit,
    # ensure threads are handled. Python's default SIGINT handler might
    # raise KeyboardInterrupt in the main thread.
    # For simplicity here, we rely on window close.
    # import signal
    # signal.signal(signal.SIGINT, lambda signum, frame: handle_closing())

    root.protocol("WM_DELETE_WINDOW", handle_closing)

    gui.update_gui()  # Start the GUI update cycle
    # The auto_get_data_var trace will call start_auto_get_data if a non-"Disabled" option is default or selected.

    root.mainloop()

    # After root.mainloop() exits (due to root.destroy()), join the aio_thread
    if gui.aio_thread.is_alive():
        print("Waiting for asyncio thread to finish...")
        gui.aio_thread.join(timeout=5) 
        if gui.aio_thread.is_alive():
            print("Asyncio thread did not finish in time.")
    print("Application closed.")
