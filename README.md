
MASAR (MAchine Snapshot, Archiving, and Retrieve) is an EPICS V4 service. The server and client are implemented in C++ and Python. The server takes machine snapshots, archives data in a relational database, and retrieves data from the database. The client provides a GUI that retrieves data, compares data with the live machine, and restores the machine with given snapshot data. The client also provides support for other python and C++ code.

The server takes machine snapshot by using pre-defined configurations. To take a snapshot the client specifies the name of the snapshot configuration and a name for this snapshot event.When the server receives a command to take a machine snapshot, the server retrieves, from the database, the list of V3 channel names for the configuration. It then gets the current value of all the channels from V3 IOC, and saves the data as a snapshot event into the database.

This repository is mainly for PyQt-based MASAR GUI being used at NSLS-II. 
