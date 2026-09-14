"""
DGSDK data type definitions

Mirrors DGDataTypes.h (structs, enums, callbacks).
"""

import ctypes
from enum import IntEnum


# =============================================================================
# Constants
# =============================================================================
MAX_JOINT_COUNT = 20
MAX_FINGER_COUNT = 5
MAX_FINGER_JOINT_COUNT = 4
CARTESIAN_COORDINATE_POSE_COUNT = 6
MAX_RECEIVED_DATA_SIZE = 1024
MAX_GRIPPER_IP_ADDRESS_SIZE = 32
MAX_GRIPPER_IP_BYTE_LENGTH = 4
MAX_COMPORT_NAME_SIZE = 32
MAX_BLEND_COUNT = 10
MAX_BLEND_ADD_POSE_COUNT = 50
MAX_RECIPE_POSE_COUNT = 100
MAX_RECIPE_GAIN_COUNT = 20
MAX_RECIPE_GRASP_COUNT = 20
MAX_GRASP_OPTION_COUNT = 2
MAX_GRIPPER_GPIO_SIZE = 4
MAX_RECEIVED_DATA_TYPE_COUNT = 8
MAX_BASE_JOINT_COUNT = 2

PI = 3.1415927
DEGREE_TO_RADIAN = PI / 180.0
RADIAN_TO_DEGREE = 180.0 / PI


# =============================================================================
# Enums
# =============================================================================
class DGResult(IntEnum):
    """SDK result — values matching DG_RESULT in DGDataTypes.h."""
    NONE = 0
    SYSTEM_SETTING_NOT_PERFORMED = 1

    VALUE_IS_NEGATIVE = 100
    OVERFLOW_JOINT_COUNT = 101
    OVERFLOW_FINGER_COUNT = 102
    OVERFLOW_TCP_COUNT = 103
    OVERFLOW_ADD_BLEND_SIZE = 105
    OVERFLOW_RECIPE_BLEND_SIZE = 106
    BLEND_SIZE_ZERO = 107
    NOT_SUPPORTED_MODEL = 108
    DATA_IS_ZERO = 109
    DATA_IS_NOT_BOOLEAN = 110
    NOT_FOUND_MODEL = 111
    OVERFLOW_RECIPE_POSE_COUNT = 112
    OVERFLOW_RECIPE_GAIN_COUNT = 113
    OVERFLOW_RECIPE_GRASP_COUNT = 114
    INVALID_CONTROL_MODE = 115
    INVALID_GRASP_MODE_DATA = 116
    OVERFLOW_GRASP_OPTION_DATA = 117
    OVERFLOW_MAX_BYTE_DATA = 118
    OVERFLOW_CURRENT_LIMIT = 119
    IS_NOT_TORQUE_CONTROL_MODE = 120
    NOT_SUPPORTED_DATA_TYPE = 121
    BACKUP_START = 122
    INVALID_PASSWORD = 123
    OVERFLOW_GPIO_COUNT = 124
    OVERFLOW_GRASP_FORCE = 125
    OVERFLOW_BLEND_WAIT_TIME = 126
    NOT_FOUND_RESTORE_DATA = 127
    RESTORE_START = 128

    NOT_ARRIVED = 200
    NOT_START_BLEND_MOVE = 201
    ALREADY_BLEND_MOVE_STATE = 202
    ALREADY_TCP_MOVE = 203
    RECIPE_IS_NOT_JOINT_MODE = 204
    ACTIVATE_CURRENT_CONTROL_MODE = 205
    ACTIVATE_GRASP_MOTION = 206
    ACTIVATE_MANUAL_CONTROL_MODE = 207

    MODULE_FAULT_1 = 401
    MODULE_FAULT_2 = 402
    MODULE_FAULT_3 = 403
    MODULE_FAULT_4 = 404
    MODULE_FAULT_5 = 405
    MODULE_FAULT_6 = 406
    MODULE_FAULT_7 = 407
    MODULE_FAULT_8 = 408
    MODULE_FAULT_9 = 409
    MODULE_FAULT_10 = 410
    MODULE_FAULT_11 = 411
    MODULE_FAULT_12 = 412
    MODULE_FAULT_13 = 413
    MODULE_FAULT_14 = 414
    MODULE_FAULT_15 = 415
    MODULE_FAULT_16 = 416
    MODULE_FAULT_17 = 417
    MODULE_FAULT_18 = 418
    MODULE_FAULT_19 = 419
    MODULE_FAULT_20 = 420
    MODULE_FAULT_21 = 421
    MODULE_FAULT_22 = 422
    MODULE_FAULT_23 = 423
    MODULE_FAULT_24 = 424
    MODULE_FAULT_25 = 425

    SOCK_EXCEPTION = 500
    SOCK_FAILED_WSA_START_UP = 501

    NO_GRASP_OBJECT = 1002
    ONLY_SUPPORTED_3FINGER = 1003
    NOT_SUPPORTED_CONTROL_MODE_OPERATOR = 1004
    NOT_SUPPORTED_CONTROL_MODE_DEVELOPER = 1005
    NOT_SUPPORTED_PORT_NUM = 1006

    PORT_EXCEPTION = 2000
    PORT_FAILED_START_UP = 2001
    PORT_SET_CONFIG_ERROR = 2002
    PORT_SET_TIMEOUT_ERROR = 2003
    PORT_SET_COMMASK_ERROR = 2004

    DIAGNOSING_SYSTEM = 2009


class DGModel(IntEnum):
    """
    Gripper model

    DGSDK 2.0.0 supports released grippers from firmware 3.0 and above.
    DG_3F_B is a legacy model and is NOT supported by DGSDK 2.0.0+.
    """
    NONE = 0x0000
    DG_1F_M = 0x1F02
    DG_2F_M = 0x2F02
    DG_3F_B = 0x3F01  # legacy, unsupported by DGSDK 2.0.0+
    DG_3F_M = 0x3F02
    DG_4F_M = 0x4F02
    DG_5F_LEFT = 0x5F12
    DG_5F_RIGHT = 0x5F22
    DG_5F_S_LEFT = 0x5F14
    DG_5F_S_RIGHT = 0x5F24
    DG_5F_S15_LEFT = 0x5F34
    DG_5F_S15_RIGHT = 0x5F44


class BlendMotionStatus(IntEnum):
    """Blend motion status"""
    STOP = 0
    RUN = 1
    COMPLETE = 2


class CommunicationMode(IntEnum):
    """Communication mode"""
    ETHERNET = 0
    RS485 = 1


class ControlMode(IntEnum):
    """Control mode"""
    OPERATOR = 0
    DEVELOPER = 1


class GainMode(IntEnum):
    """Gain mode"""
    PD = 0
    PID = 1


class DeveloperModeCommand(IntEnum):
    """Developer-mode command"""
    GET_DATA = 0x01
    SET_RECEIVED_DATA = 0x02
    SET_DUTY = 0x05
    SET_GPIO = 0x06
    SET_IP_ADDRESS = 0x07
    GET_ID_AND_VERSION = 0x08
    GET_JOINT_ID = 0x09
    SET_BOOT_MODE = 0x0A
    SET_FT_OFFSET_ZERO = 0x0B


class ReceivedDataType(IntEnum):
    """Received data type — selects what the gripper streams back."""
    JOINT = 0x01
    CURRENT = 0x02
    TEMPERATURE = 0x03
    VELOCITY = 0x04
    FINGER_FT_SENSOR = 0x05
    GPIO = 0x06
    MODULE_ERROR_CODE = 0x07
    CONTROL_PERIOD = 0x08


class DGGraspMode(IntEnum):
    """Grasp mode — finger/model-specific presets (see DG_GRASP_MODE)."""
    NONE = 0

    # 3F modes
    _3F_3FINGER = 1
    _3F_2FINGER_1_AND_2 = 2
    _3F_2FINGER_1_AND_3 = 3
    _3F_2FINGER_2_AND_3 = 4
    _3F_3FINGER_PARALLEL = 5
    _3F_3FINGER_ENVELOP = 6

    # 5F modes
    _5F_5FINGER = 21
    _5F_3FINGER = 22
    _5F_3FINGER_PARALLEL = 23
    _5F_2FINGER_1_AND_2 = 24
    _5F_2FINGER_1_AND_3 = 25
    _5F_2FINGER_1_AND_4 = 26
    _5F_2FINGER_1_AND_5 = 27
    _5F_5FINGER_PARALLEL = 28
    _5F_5FINGER_ENVELOP = 29

    # 4F modes
    _4F_4FINGER = 31
    _4F_4FINGER_PARALLEL = 32
    _4F_4FINGER_ENVELOP = 33
    _4F_4FINGER_RIGHT_PARALLEL = 34
    _4F_4FINGER_LEFT_PARALLEL = 35
    _4F_2FINGER_1_AND_2 = 36
    _4F_2FINGER_1_AND_4 = 37
    _4F_2FINGER_3_AND_4 = 38

    # 2F modes
    _2F_2FINGER = 51
    _2F_2FINGER_ENVELOP = 52


class DGGraspOption(IntEnum):
    """Grasp option"""
    NONE = 0
    PARALLEL = 1
    FIX_TILT = 2
    SET_TILT = 3


class DGDiagnosis(IntEnum):
    """Diagnosis state — step and final result values."""
    STEP_JOINT_ID = 1
    STEP_PERIOD = 2
    STEP_TEMPERATURE = 3
    STEP_JOINT = 4

    RESULT_NONE = 5
    RESULT_STANDBY = 6

    RESULT_OK = 100
    RESULT_FAULT = 200


class DGSensorType(IntEnum):
    """Fingertip sensor type"""
    FT_SENSOR_6_AXIS = 1
    FT_SENSOR_3_AXIS = 2
    TACTILE_M = 3
    FT_SENSOR_4_AXIS = 4
    TACTILE_S = 5


# =============================================================================
# Structures
# =============================================================================
class ReceivedGripperData(ctypes.Structure):
    """Gripper state frame"""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("joint", ctypes.c_float * MAX_JOINT_COUNT),
        ("current", ctypes.c_int * MAX_JOINT_COUNT),
        ("velocity", ctypes.c_int * MAX_JOINT_COUNT),
        ("temperature", ctypes.c_float * MAX_JOINT_COUNT),
        ("TCP", ctypes.c_float * (6 * MAX_FINGER_COUNT)),
        ("moving", ctypes.c_int),
        ("targetArrived", ctypes.c_int),
        ("blendMoveState", ctypes.c_int),
        ("currentBlendIndex", ctypes.c_int),
        ("productID", ctypes.c_int),
        ("firmwareVersion", ctypes.c_int),
        ("moduleErrorCode", ctypes.c_int),
        ("controlPeriod", ctypes.c_int),
    ]

    def to_dict(self):
        """Convert to dict"""
        return {
            "joint": list(self.joint),
            "current": list(self.current),
            "velocity": list(self.velocity),
            "temperature": list(self.temperature),
            "TCP": list(self.TCP),
            "moving": self.moving,
            "targetArrived": self.targetArrived,
            "blendMoveState": self.blendMoveState,
            "currentBlendIndex": self.currentBlendIndex,
            "productID": self.productID,
            "firmwareVersion": self.firmwareVersion,
            "moduleErrorCode": self.moduleErrorCode,
            "controlPeriod": self.controlPeriod,
        }


class RecipeBlendData(ctypes.Structure):
    """Recipe for blend motion"""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("recipePoseNumber", ctypes.c_int),
        ("recipeGainNumber", ctypes.c_int),
        ("blendWaitTime", ctypes.c_int),
        ("number", ctypes.c_int),
    ]


class GripperSystemSetting(ctypes.Structure):
    """Gripper system"""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("comport", ctypes.c_char * MAX_COMPORT_NAME_SIZE),
        ("ip", ctypes.c_char * MAX_GRIPPER_IP_ADDRESS_SIZE),
        ("port", ctypes.c_int),
        ("readTimeout", ctypes.c_int),
        ("controlMode", ctypes.c_int),
        ("communicationMode", ctypes.c_int),
        ("slaveID", ctypes.c_int),
        ("baudrate", ctypes.c_int),
    ]

    @classmethod
    def create(cls, ip="192.168.1.100", port=8000,
               control_mode=ControlMode.OPERATOR,
               communication_mode=CommunicationMode.ETHERNET,
               read_timeout=1000, slave_id=1, baudrate=115200,
               comport="COM1"):
        """Build a GripperSystemSetting"""
        setting = cls()
        setting.ip = ip.encode() if isinstance(ip, str) else ip
        setting.port = port
        setting.controlMode = control_mode
        setting.communicationMode = communication_mode
        setting.readTimeout = read_timeout
        setting.slaveID = slave_id
        setting.baudrate = baudrate
        setting.comport = comport.encode() if isinstance(comport, str) else comport
        return setting


class GripperSetting(ctypes.Structure):
    """Gripper option setting"""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("jointOffset", ctypes.c_float * MAX_JOINT_COUNT),
        ("jointInpose", ctypes.c_float * MAX_JOINT_COUNT),
        ("tcpInpose", ctypes.c_float * MAX_FINGER_COUNT),
        ("orientationInpose", ctypes.c_float * MAX_FINGER_COUNT),
        ("receivedDataType", ctypes.c_int * MAX_RECEIVED_DATA_TYPE_COUNT),
        ("movingInpose", ctypes.c_float),
        ("jointCount", ctypes.c_int),
        ("fingerCount", ctypes.c_int),
        ("model", ctypes.c_int),
        ("dutyByteLength", ctypes.c_int8),
    ]

    @classmethod
    def create(cls, model, joint_count, finger_count,
               moving_inpose=0.5, received_data_type=None):
        """
        Build a GripperSetting

        Args:
            model: DGModel enum (e.g. DGModel.DG_3F_M). DG_3F_B is NOT supported by DGSDK 2.0.0+.
            joint_count: total joint count
            finger_count: finger count
            moving_inpose: angle threshold for "moving" detection (default 0.5)
            received_data_type: list selecting streamed data types
                                (default [JOINT, CURRENT, 0, 0, 0, 0, 0]).
        """
        setting = cls()
        setting.model = int(model)
        setting.jointCount = joint_count
        setting.fingerCount = finger_count
        setting.movingInpose = moving_inpose

        # zero defaults
        for i in range(MAX_JOINT_COUNT):
            setting.jointOffset[i] = 0.0
            setting.jointInpose[i] = 0.0

        for i in range(MAX_FINGER_COUNT):
            setting.tcpInpose[i] = 0.0
            setting.orientationInpose[i] = 0.0

        # received data type selection
        if received_data_type is None:
            received_data_type = [1, 2, 0, 0, 0, 0, 0]  # JOINT, CURRENT
        for i, val in enumerate(received_data_type):
            if i < MAX_RECEIVED_DATA_TYPE_COUNT:
                setting.receivedDataType[i] = val

        return setting


class RecipePoseData(ctypes.Structure):
    """Recipe pose data— target joints + per-joint motion time."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("targetJoint", ctypes.c_float * MAX_JOINT_COUNT),
        ("jointMotionTime", ctypes.c_int * MAX_JOINT_COUNT),
        ("number", ctypes.c_int),
        ("mode", ctypes.c_int),
    ]


class RecipeGainData(ctypes.Structure):
    """Recipe gain data— P/D/I gains + error-integral limit."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("gainP", ctypes.c_float * MAX_JOINT_COUNT),
        ("gainD", ctypes.c_float * MAX_JOINT_COUNT),
        ("gainI", ctypes.c_float * MAX_JOINT_COUNT),
        ("iLimit", ctypes.c_float * MAX_JOINT_COUNT),
        ("controlPIDMode", ctypes.c_int),
        ("number", ctypes.c_int),
        ("mode", ctypes.c_int),
    ]


class RecipeGraspData(ctypes.Structure):
    """Recipe grasp data— grasp mode/force/option + per-joint position mode."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("graspForce", ctypes.c_float),
        ("positionMode", ctypes.c_int * MAX_JOINT_COUNT),
        ("graspMode", ctypes.c_int),
        ("graspOption", ctypes.c_int),
        ("smoothGrasping", ctypes.c_int),
        ("number", ctypes.c_int),
    ]


class ReceivedFingertipSensorData(ctypes.Structure):
    """Fingertip sensor frame— FT values + tactile grid (see DGSensorType)."""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("sensorType", ctypes.c_int),
        ("attachedFinger", ctypes.c_int * MAX_FINGER_COUNT),
        ("forceTorque", ctypes.c_float * (6 * MAX_FINGER_COUNT)),
        ("tactile", ctypes.c_uint16 * (18 * MAX_FINGER_COUNT)),
    ]

    def to_dict(self):
        """Convert to dict"""
        return {
            "sensorType": self.sensorType,
            "attachedFinger": list(self.attachedFinger),
            "forceTorque": list(self.forceTorque),
            "tactile": list(self.tactile),
        }


class ReceivedGPIOData(ctypes.Structure):
    """GPIO data"""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("GPIO", ctypes.c_int * MAX_GRIPPER_GPIO_SIZE),
    ]

    def to_dict(self):
        """Convert to dict"""
        return {"GPIO": list(self.GPIO)}


class DiagnosisSystem(ctypes.Structure):
    """Diagnosis result"""
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [
        ("process", ctypes.c_int),
        ("step", ctypes.c_int),
        ("jointId", ctypes.c_int),
        ("period", ctypes.c_int),
        ("joint", ctypes.c_int),
        ("temperature", ctypes.c_int),
    ]

    def to_dict(self):
        """Convert to dict"""
        return {
            "process": self.process,
            "step": self.step,
            "jointId": self.jointId,
            "period": self.period,
            "joint": self.joint,
            "temperature": self.temperature,
        }


# =============================================================================
# Callback Types
# =============================================================================
ReceivedGripperDatasCallback = ctypes.CFUNCTYPE(None, ReceivedGripperData)
ConnectedToGripperCallback = ctypes.CFUNCTYPE(None)
DisconnectedToGripperCallback = ctypes.CFUNCTYPE(None)
CommunicationPeriodCallback = ctypes.CFUNCTYPE(None, ctypes.c_int)
DiagnosisSystemCallback = ctypes.CFUNCTYPE(None, DiagnosisSystem)
ReceivedSensorCallback = ctypes.CFUNCTYPE(None, ReceivedFingertipSensorData)
ReceivedGPIOCallback = ctypes.CFUNCTYPE(None, ReceivedGPIOData)
DataProcessingCallback = ctypes.CFUNCTYPE(None, ctypes.c_int)
