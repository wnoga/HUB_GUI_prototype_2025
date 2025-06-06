import numpy as np
import socket
import threading
import time
import queue
import tkinter as tk
import signal
import json
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from multiprocessing import Pool
import argparse
import os


def _appen_data(data):
    toRet = []
    for d in data:
        tmp = d.get("last_data", None)
        if tmp:
            toRet.append(tmp)
    return toRet


class HubInterface:
    """
    A class for managing a connection to a hub over a network socket.
    """

    def __init__(self, ip="192.168.1.100", port=5555):
        """
        Initializes the HubInterface with default values.
        """
        self.ip = ip
        self.port = port
        self.thread = None
        # self.receive_queue = queue.Queue()
        # self.send_queue = queue.Queue()
        self.s: socket.socket = None
        self.connected = False
        # self.use_receiving_thread = use_receiving_thread
        self.timeout_s = 20
        # self.receive_thread_should_run = False
        # self.receive_thread = None
        # self.receive_queue = queue.Queue()

    def connect(self, retry=True):
        """
        Establishes a connection to the hub at the specified IP and port.
        """
        try:
            if self.s:
                self.s.close()
        except:
            pass
        self.connected = False
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.connect((self.ip, self.port))
        self.connected = True
        # Set a timeout for the socket operations
        self.s.settimeout(self.timeout_s)

        # print("USE RECEIVE THREAD:", self.use_receiving_thread)
        # if self.use_receiving_thread:
        #     # Start a thread to continuously receive data
        #     self.receive_thread_should_run = True
        #     self.receive_thread = threading.Thread(target=self._receive_loop)
        #     self.receive_thread.daemon = True
        #     self.receive_thread.start()

    def _receive_loop(self):
        while self.receive_thread_should_run:
            data = self._receive()
            if data:
                self.receive_queue.put(data)
                print(f"Received: {data}")
        print("receive_thread_should_run exit")

    def send(self, data, waitForResponseData=True):
        """
        Sends data to the connected hub and receives a response.

        Args:
            data (str): The data to send.

        Returns:
            dict or None: The received JSON data as a dictionary, or None if an error occurred.
        """
        print(f"Try send: {data}")
        try:
            # if not self.connected:
            # dont block on failed connection try
            self.connect(retry=False)
            if not self.connected:
                return {"status": "ERROR", "message": "Not connected"}

            self.s.sendall(data.encode())
            response_data = None
            if waitForResponseData:
                response_data = self.receive()
            # try:
            # self.s.shutdown(socket.SHUT_RDWR)
            self.s.close()
            # # except Exception as e:
            # # print("Error close socket", e)

            # self.connected = False # Connection is usually closed after sending a command and receiving a response
            #     pass
            self.connected = False
            return {"status": "OK", "data": response_data}
        except Exception as e:
            print(f"Error sending data: {e}")
            self.connected = False
            return {"status": "ERROR", "message": str(e)}

    def _receive(self):
        if not self.connected:
            return None
        try:
            # self.s.settimeout(0.1) # Set a small timeout to not block indefinitely if no data
            chunk = self.s.recv(1024)
            if not chunk:
                # self.connected = False # Assuming connection is closed
                return None
            # while True:
                # Continue receiving if more data is available
            return chunk.decode()
        except socket.timeout:
            return None  # Timeout, no data received yet

    def receive(self): # TODO this does not check for connection status during loop
        toReturn = ''
        # if self.use_receiving_thread:
        #     start_time = time.time()
        #     while self.receive_queue.empty() and (time.time() - start_time) < 5.0:  # Poll for 1 second
        #         pass
        #     while not self.receive_queue.empty():
        #         toReturn += self.receive_queue.get()
        #     # print(toReturn)
        #     return toReturn
        # else:
        # Poll for self.timeout_s seconds
        start_time = time.time() # Start time of polling
        while (time.time() - start_time) < self.timeout_s: # Polling duration
            tmp = self._receive()
            if tmp:
                toReturn += tmp
            try:
                json.loads(toReturn) # Try to parse as JSON
                return toReturn
            except:
                pass
        if toReturn == '':
            return None
        return toReturn


class App:
    def __init__(self, master: tk.Tk, ip="192.168.1.100", port=5555):
        self.master = master
        master.title("HUB Interface")
        self.app_running = True

        self.ip = None
        self.hub = None

        self.port = None

        self.response_text_queue = queue.Queue()

        self.afe_id_new_list = None
        self.afe_id = None
        self.afe_id_all = []

        self.plot_data_changed = False # Flag to indicate if new data is available for plotting
        self.plot_main_frame = None # Frame to hold matplotlib canvases

        self.data_to_plot = {}
        # self.data_to_plot_len_last = 0

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
        
        
        self.hub = HubInterface(ip=self.ip, port=self.port)
        self.change_ip_and_port()

        self.auto_get_data_after_id = None # To store the ID of the after job for automatic data fetching

    def quit(self):
        print("quittt")
        self.app_running = False # Stop the update_gui loop
        if self.hub and self.hub.connected:
            # self.hub.connected = False # This is handled by send closing the socket
            self.hub.s.close()

    # def connect_hub(self):
    #     try:
    #         self.hub.connect()
    #         self.response_text.insert(
    #             tk.END, f"Connected to HUB at {self.hub.ip}:{self.hub.port}\n")
    #         self.update_gui()  # Start polling for messages
    #     except Exception as e:
    #         self.response_text.insert(
    #             tk.END, f"Failed to connect to HUB: {e}\n")

    # def disconnect_hub(self):
    #     if self.hub.connected:
    #         self.hub.connected = False
    #         self.hub.s.close()
    #         self.response_text.insert(tk.END, "Disconnected from HUB.\n")

    # def update_afe_dropdown(self, afe_ids):
    #     menu = self.afe_id_dropdown["menu"]
    #     menu.delete(0, "end")  # Clear previous items
    #     if afe_ids:
    #         sorted_ids = sorted(afe_ids, key=int) if all(
    #             id.isdigit() for id in afe_ids) else sorted(afe_ids)
    #         self.afe_id_var.set(sorted_ids[0])  # Set default selection
    #         for afe_id_str in sorted_ids:
    #             menu.add_command(label=afe_id_str, command=tk._setit(
    #                 self.afe_id_var, afe_id_str))
    #     else:
    #         self.afe_id_var.set("N/A")  # No AFEs found
    #         menu.add_command(
    #             label="N/A", command=tk._setit(self.afe_id_var, "N/A"))

    # def refresh_afe_list(self):
    #     """Sends a command to the hub to get the list of connected AFEs and updates the dropdown."""
    #     try:
    #         command_json = {"procedure": "get_all_afe_configuration"}
    #         command_str = json.dumps(command_json)
    #         response = self.hub.send(command_str)
    #         self.response_text.insert(tk.END, f"Sent: {command_str}\n")
    #         # The actual AFE data will arrive via the receiving thread/polling

    #     except Exception as e:
    #         self.response_text.insert(
    #             tk.END, f"Error refreshing AFE list: {e}\n")

    # def update_gui(self):
    #     """Polls the receive queue for messages and updates the GUI."""
    #     print("update ghuiii")
    #     while not self.hub.receive_queue.empty():
    #         message_raw = self.hub.receive_queue.get()
    #         try:
    #             message_json = json.loads(message_raw)
    #             self.response_text.insert(
    #                 tk.END, f"Received: {json.dumps(message_json)}\n")

    #             # Check if the received message is AFE configuration data
    #             # AFE configuration data is expected to be a dictionary where keys are AFE IDs (strings)
    #             # and values are their configurations.
    #             # Example: {'36': {'ID': 36, ...}, '35': {'ID': 35, ...}}
    #             # We can identify this by checking if the values are also dictionaries and contain 'ID'
    #             is_afe_config_data = all(
    #                 isinstance(val, dict) and 'ID' in val for val in message_json.values()
    #             )

    #             if is_afe_config_data:
    #                 afe_ids_from_response = list(message_json.keys())
    #                 self.update_afe_dropdown(afe_ids_from_response)

    #         except json.JSONDecodeError:
    #             self.response_text.insert(
    #                 tk.END, f"Received raw: {message_raw}\n")
    #         except Exception as e:
    #             self.response_text.insert(
    #                 tk.END, f"Error processing received message: {e}\n")

    #     # Schedule the next poll
    #     self.master.after(100, self.update_gui)

    def send_command(self):
        if not self.hub.connected:
            self.hub.connect(retry=False)
            if not self.hub.connected:
                self.response_text.insert(tk.END, "Not connected to HUB.\n")
                return

        command_str = self.command_entry.get()
        try:
            command_json = json.loads(command_str)
            response = self.hub.send(json.dumps(command_json))
            self.response_text.insert(tk.END, f"Sent: {command_str}\n")
            # self.response_text.insert(tk.END, f"Received: {response}\n")
        except json.JSONDecodeError:
            self.response_text.insert(tk.END, "Invalid JSON format\n")
        except Exception as e:
            self.response_text.insert(tk.END, f"Error sending command: {e}\n")

    def change_ip_and_port(self, event=None):
        """Changes the HUB IP address."""
        new_ip = self.ip_entry.get()
        new_port = int(self.port_entry.get())

        self.ip = new_ip
        self.port = new_port

        # self.hub.ip = new_ip
        # self.hub.connected = False  # Force reconnection on next send
        self.response_text.insert(
            tk.END, f"HUB IP changed to {new_ip}:{new_port}. Connection will be re-established on next command.\n")

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

    # def shared_get(self, entry=None):
    #     # print("shared_get", entry)
    #     # self.shared_entry_get = entry.get()
    #     self.shared_entry_get = self.ip_entry.get()

    def thread_send_command(self, command_json):
        ip = self.ip
        port = self.port
        hub = HubInterface(ip=ip, port=port) # Create a new instance for each thread
        command_str = json.dumps(command_json)
        try:
            response = hub.send(
                command_str, waitForResponseData=self.isThisCommandReturnData(command_json["procedure"]))
            gui_timestamp = time.time()
            self.response_text_queue.put(
                (tk.END, f"Sent: {command_str} -> {response.get("status", "ERROR")}\n"))
            procedure = command_json.get("procedure", None)
            if procedure == None:
                print("No procedure specified")
            elif procedure == "get_all_afe_configuration":
                if not response.get("data"):
                    print("No response data")
                    return
                response_data = json.loads(response["data"])
                afe_ids_from_response = list(response_data.keys())
                if afe_ids_from_response:
                    # Sort IDs for consistent order in dropdown, e.g., numerically
                    try:
                        afe_ids_sorted = sorted(afe_ids_from_response, key=int)
                    except ValueError:  # Handle non-integer IDs if they can occur
                        afe_ids_sorted = sorted(afe_ids_from_response)
                    self.afe_id_new_list = afe_ids_sorted

            elif procedure == "default_get_measurement_last":
                # print("default_get_measurement_last")
                # print(response)
                response_data = json.loads(response["data"])
                device_id = response_data.get("device_id", None)
                if device_id:
                    if not self.data_to_plot.get(device_id, None):
                        self.data_to_plot[device_id] = {}
                    toAppend = response_data.get("retval", None)
                    if toAppend:
                        for k, v in toAppend.items():
                            # Add device_id and gui_timestamp to each individual measurement dictionary
                            v["device_id"] = device_id
                            v["gui_timestamp"] = gui_timestamp # Use the GUI's timestamp of receiving the response
                            # v["timestamp_datetime"] = pd.to_datetime(v["timestamp_ms"], unit='ms') # Convert HUB timestamp to datetime
                            v["gui_datetime"] = pd.to_datetime(v["gui_timestamp"], unit='s') # Convert GUI timestamp to datetime

                            df = pd.DataFrame([v]) # Create a DataFrame from the single measurement dictionary

                            print("X:",self.data_to_plot[device_id].get(k, None))
                            # if not self.data_to_plot[device_id].get(k, None):
                            
                            if k in self.data_to_plot[device_id]:
                                # print(self.data_to_plot[device_id][k])
                                # print(df)
                                self.data_to_plot[device_id][k] = pd.concat([self.data_to_plot[device_id][k],df],ignore_index=True)
                            else:
                                self.data_to_plot[device_id][k] = df
                            self.data_to_plot[device_id][k].sort_values(by="gui_timestamp",inplace=True)
                            # print(self.data_to_plot[device_id][k])
                            
                        self.plot_data_changed = True # Signal that data has been updated for plotting

                            # # self.data_to_plot[device_id].
                            # if not self.data_to_plot[k]:
                            #     self.data_to_plot[k] = [toAppend[k]]
                            # else:
                            #     pd.concat([self.data_to_plot[k], toAppend[k]], ignore_index=True)
                            # self.data_to_plot[k].sort_values(["timestamp_ms"], inplace=True)

                        # self.data_to_plot[device_id]
                        # print(toAppend)

                        # self.data_to_plot[device_id].append(toAppend)

                    # self.data_to_plot
                    # self.plot_data(response_data) # Plot data in separate window
                        # (tk.END, f"Measurement Data: {json.dumps(response_data)}\n"))
                    # self.response_text.insert(
                    #     tk.END, f"Measurement Data: {json.loads(response_data)}\n")
            elif procedure == "default_procedure":
                response = self.hub.receive()
                self.response_text.insert(
                    tk.END, f"Default Procedure Response: {json.loads(response)}\n")
            elif procedure == "default_set_dac":
                response = self.hub.receive()
                self.response_text.insert(
                    tk.END, f"Set DAC Response: {json.loads(response)}\n")
            elif procedure == "default_hv_set":
                response = self.hub.receive()
                self.response_text.insert(
                    tk.END, f"HV Set Response: {json.loads(response)}\n")

        except Exception as e:
            self.response_text_queue.put(
                (tk.END, f"Error sending command: {e}\n"))

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

        if self.data_to_plot:
            columns_to_plot = [
                # 'calculation_timestamp_ms',
                # 'timestamp_ms',
                # 'DC_LEVEL_MEAS0', 'DC_LEVEL_MEAS1',
                'U_SIPM_MEAS0', 'U_SIPM_MEAS1',
                'I_SIPM_MEAS0', 'I_SIPM_MEAS1',
                'TEMP_EXT', 'TEMP_LOCAL'
            ]
            
            figures_created = [] # Keep track of figures to close them later

            # Create a new figure and axes for each data type (e.g., 'last_data') per device
            fig, axes = plt.subplots(3, 1, sharex=True, figsize=(7, 8)) # 3 rows, 1 column
            figures_created.append(fig) # Add figure to list for closing
            color_map = plt.colormaps.get_cmap('tab20')
            # time_column = "timestamp_ms"
            # time_column = "timestamp_datetime"
            time_column = "gui_timestamp"
            plot_color_idx = 0
            for device_id, device_data_types in self.data_to_plot.items():
                for data_name, df in device_data_types.items():
                    if df.empty:
                        continue # Skip empty DataFrames

                    # fig.suptitle(f"AFE {device_id} - {data_name}", fontsize=10)
                    
                    if time_column not in df.columns:
                        print(f"Warning: Time column '{time_column}' not in DataFrame for {device_id} - {data_name}")
                        continue
                    if "ms" in time_column:
                        axes[-1].set_xlabel(f"{time_column} (ms)")
                    elif "datetime" in time_column:
                        axes[-1].set_xlabel(f"{time_column}")
                    else:
                        axes[-1].set_xlabel(time_column)
                                            
                    for col_name in columns_to_plot:
                        if col_name not in df.columns:
                            continue
                        color = plot_color_idx
                        ax_idx = -1
                        if "TEMP" in col_name:
                            ax_idx = 0
                            if "EXT" in col_name: color = color + 1
                        elif "U_SIPM" in col_name:
                            ax_idx = 1
                            if "MEAS1" in col_name: color = color + 1
                        elif "I_SIPM" in col_name:
                            ax_idx = 2
                            if "MEAS1" in col_name: color = color + 1
                        
                        if ax_idx != -1:
                            axes[ax_idx].plot(df[time_column], df[col_name], 
                                              color=color_map(color), label=f"AFE{device_id} {col_name}", marker='o', linestyle='-') # Add markers
                            # # axes[ax_idx].set_ylabel(col_name.replace("_", " "), fontsize=8)
                            # axes[ax_idx].tick_params(axis='y', labelsize=7)
                            # axes[ax_idx].grid(True, linestyle=':', alpha=0.7)
                    
                plot_color_idx += 2
                
            for ax_obj in axes:
                if ax_obj.has_data(): # Only add legend if there's data plotted on this axis
                    ax_obj.legend(loc='upper left', fontsize='x-small')
                    ax_obj.tick_params(axis='x', labelsize=7)
                    ax_obj.grid(True, linestyle=':', alpha=0.7)
            axes[0].set_ylabel(r"TEMP [$^{\circ}$C]")
            axes[1].set_ylabel(r"U SiPM [V]")
            axes[2].set_ylabel(r"I SiPM [A]")
            fig.tight_layout(rect=[0, 0.03, 1, 0.95]) # Adjust for suptitle and xlabel
            # Embed the matplotlib figure into the Tkinter frame
            canvas_agg = FigureCanvasTkAgg(fig, master=self.plot_main_frame)
            canvas_agg.draw()
            # Pack the canvas widget into the main plot frame
            canvas_agg.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

            # Close all matplotlib figures created during this call to free memory
            for fig_to_close in figures_created:
                plt.close(fig_to_close)

            # print(data)
            # data = self.data_to_plot
            # print(data)

        # if "retval" in data and "last_data" in data["retval"]:
        #     print(data["retval"])
        #     # last_data = data["retval"]["last_data"]
        #     # measurements = ["U_SIPM_MEAS0", "U_SIPM_MEAS1",
        #     #                 "I_SIPM_MEAS0", "I_SIPM_MEAS1"]  # Example measurements
        #     # x = list(range(len(measurements)))
        #     # y = [last_data.get(key, 0) for key in measurements]

        #     # # Basic bar chart (you can customize this further)
        #     # bar_width = 50
        #     # x_offset = 50
        #     # y_offset = 50
        #     # max_value = max(y) if y else 1

        #     # for i, value in enumerate(y):
        #     #     bar_height = (value / max_value) * 200  # Scale to 200 pixels
        #     #     self.canvas.create_rectangle(x_offset + i * (bar_width + 20), 250 - bar_height,
        #     #                                 x_offset + (i + 1) * bar_width + i * 20, 250, fill="blue")
        #     #     self.canvas.create_text(x_offset + i * (bar_width + 20) + bar_width / 2, 260, text=measurements[i], anchor=tk.N)
    def start_auto_get_data(self, *args): # Accept *args for trace compatibility
        """
        Manages the automatic data fetching process based on the dropdown selection.
        This method is called by the dropdown menu's trace, by scheduled 'after' events,
        and initially when the app starts.
        """
        # Always cancel any existing timer. This handles changes in selection,
        # ensures only one timer runs, and correctly stops when "Disabled" is chosen.
        if self.auto_get_data_after_id:
            self.master.after_cancel(self.auto_get_data_after_id)
            self.auto_get_data_after_id = None

        selected_option = self.auto_get_data_var.get()
        print(f"Auto Get Data: Selection changed to '{selected_option}' or timer fired.")

        if selected_option == "Disabled":
            return # Timer is cancelled, nothing more to do.

        # Extract seconds from the option string (e.g., "5 s" -> 5)
        try:
            seconds_str = selected_option.split(" ")[0]
            interval_ms = int(seconds_str) * 1000
        except (ValueError, IndexError):
            print(f"Error parsing interval from '{selected_option}'. Stopping auto-fetch.")
            return # Do not proceed if interval is invalid; timer is already cancelled.

        # Perform the data fetch immediately since a valid interval is active.
        self.get_data_for_all_afes()

        # Schedule the next call to this function.
        print(f"Scheduling next auto data fetch in {interval_ms} ms.")
        self.auto_get_data_after_id = self.master.after(interval_ms, self.start_auto_get_data)
    def stop_auto_get_data(self):
        """Stops the automatic data fetching process."""
        if self.auto_get_data_after_id:
            self.master.after_cancel(self.auto_get_data_after_id)
            self.auto_get_data_after_id = None # Ensure it's cleared
    # This function is triggered by buttons in the GUI. It creates a new thread to send the command so the GUI doesn't freeze.
    def send_predefined_command(self, command_json):
        t = threading.Thread(target=self.thread_send_command,
                             args=(command_json,), daemon=True)
        t.start()

    def get_data_for_all_afes(self):
        """Sends 'default_get_measurement_last' to all known AFE IDs."""
        if self.afe_id_all:
            for afe_id_str in self.afe_id_all:
                try:
                    self.send_predefined_command({"afe_id": int(afe_id_str), "procedure": "default_get_measurement_last"})
                except ValueError:
                    self.response_text_queue.put((tk.END, f"Invalid AFE ID for 'Get Data All': {afe_id_str}\n"))
        else:
            self.response_text_queue.put((tk.END, "No AFE IDs known. Press 'Get Config' first.\n"))
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
        self.master.after(100, self.update_gui)  # Poll every 100ms


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HUB GUI Interface")
    parser.add_argument("--ip", type=str, default="10.42.0.92", help="HUB IP address")
    parser.add_argument("--port", type=int, default=5555, help="HUB port number")
    args = parser.parse_args()
    
    # hub = HubInterface('10.42.0.100')
    # hub = HubInterface(args.ip, args.port)

    # hub.connect()
    # toSend = {"afe_id": 35, "procedure": "default_get_measurement_last"}
    # response = hub.send(str(toSend).replace("'", "\""))
    # print("Response:", response)

    # toSend = {"procedure": "get_all_afe_configuration"}
    # response = hub.send(str(toSend).replace("'", "\""))
    # print("Response:", response)
    state = 0
    while False:
        time.sleep(1)
        if state == 0:
            toSend = {"afe_id": 35, "procedure": "default_full"}
            response = hub.send(str(toSend).replace("'", "\""))
            try:
                print("Response:", response)
                if "status" in response:
                    if response["status"] == "OK":
                        state = 1
            except Exception as e:
                print("Error:", e, response)

        elif state == 1:
            toSend = {"afe_id": 35, "procedure": "default_get_measurement_last"}
            response = hub.send(str(toSend).replace("'", "\""))
            print("Response:", response)
            time.sleep(4)
    if False:
        # if 1:
        # hub.send(f'{"test":{np.round(np.random.uniform(0.0,1.0),2)}}')
        toSend = {"test": np.round(np.random.uniform(0.0, 1.0), 2)}
        # toSend = json(toSend)
        toSend = str(toSend).replace("'", "\"")
        hub.send(toSend)
        time.sleep(4)
        # time.sleep(1)

    root = tk.Tk()
    gui = App(root,ip=args.ip, port=args.port)

    def handle_closing():
        print("CLOSING APP")
        gui.app_running = False
        gui.stop_auto_get_data() # Stop the automatic data fetching timer
        root.destroy()
        # exit(0) # This might be necessary depending on thread behavior

    def handle_abort(event=None):
        print("HANDLE ABORT (CTRL+C)")

    signal.signal(signal.SIGINT, lambda signum,
                  frame: handle_closing())  # Catch Ctrl+C
    # Catch window closing event
    root.protocol("WM_DELETE_WINDOW", handle_closing)
    # root.bind('<Control-q>', handle_abort) # Example binding

    # Start the automatic data fetching when the GUI starts

    # Start the GUI event loop
    def run_loop():
        gui.update_gui()
        gui.start_auto_get_data()
        while gui.app_running:
            root.update()
    run_loop()
