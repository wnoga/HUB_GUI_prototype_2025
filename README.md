# HUB_GUI_prototype_2025

## Project Description

This repository contains a prototype for the graphical user interface (GUI) of the HUB interface. The project aims to create a user-friendly and intuitive interface for interacting with the HUB.

## Features (Planned/Implemented)

*   **Data Visualization:** Display various types of data from the HUB in a clear and understandable manner (e.g., graphs, charts, tables).
*   **Control Panel:** Provide controls for interacting with the HUB and initiating actions.
*   **Real-time Updates:** Display real-time data and status information from the HUB.
*   **User Authentication:** Secure access to the interface with user login.
*   **Configuration Options:** Allow users to configure various aspects of the interface and data display.

### Installation

1.  Clone the repository: `git clone https://github.com/blondier94/HUB_GUI_prototype_2025.git`
2.  Navigate to the project directory: `cd HUB_GUI_prototype_2025`
3.  Install dependencies: `pip install -r requirements.txt`

### Running the Prototype

Run `python hub_interface.py` to start the GUI

### Configuration

The prototype relies on a DHCP server configuration file (e.g., `dhcpd.conf`) to obtain network information. Ensure your DHCP server is configured to provide the necessary parameters for the HUB. A typical configuration might include:

```
subnet 192.168.1.0 netmask 255.255.255.0 {
  range 192.168.1.10 192.168.1.100;
  option routers 192.168.1.1;
  option domain-name-servers 8.8.8.8, 8.8.4.4;
}
```


*   **macOS:** Use "Internet Sharing" found in System Settings (or System Preferences) > Sharing. You can choose to share your connection from Ethernet to other computers using Ethernet or Wi-Fi.
*   **Linux:** This can be achieved in several ways, depending on your distribution and setup:
    *   Using NetworkManager: Many desktop environments provide a graphical way to set up a shared or "hotspot" connection.
        *   **Fedora:** You can typically configure this through the GNOME Settings panel under Network or Wi-Fi (for creating a hotspot). Select your wired connection, go to its settings (often a gear icon), and look for an "IPv4" tab where you can set the "Method" to "Shared to other computers". Alternatively, `nm-connection-editor` (Network Connections tool) provides a more detailed interface.
    *   Using `iptables` for Network Address Translation (NAT) and enabling IP forwarding via `sysctl`.
    *   Using `systemd-networkd` for more advanced network configurations.

For detailed, step-by-step instructions, search online for guides specific to your operating system version (e.g., "share wired internet windows 11", "macOS Sonoma internet sharing", "ubuntu share ethernet connection").
For detailed, step-by-step instructions, search online for guides specific to your operating system version (e.g., "share wired internet windows 11", "macOS Sonoma internet sharing", "Fedora share ethernet connection", "ubuntu share ethernet connection").




---