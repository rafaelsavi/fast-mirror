from enum import Enum


class BackendThreadStatus(Enum):
    STANDBY = 'Standby'
    RUNNING = 'Running'
    STOPPING = 'Stopping'


class TkinterCfgRelief(Enum):
    SUNKEN = 'sunken'
    RAISED = 'raised'


class TkinterCfgState(Enum):
    NORMAL = 'normal'
    DISABLED = 'disabled'
    HIDDEN = 'hidden'

    @classmethod
    def from_bool(cls, value: bool) -> str:
        return cls.NORMAL.value if value else cls.DISABLED.value
