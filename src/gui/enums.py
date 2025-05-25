from enum import Enum


class BackendThreadStatus(Enum):
    STANDBY = 'Standby'
    RUNNING = 'Running'
    STOPPING = 'Stopping'


class Relief(Enum):
    SUNKEN = 'sunken'
    RAISED = 'raised'
