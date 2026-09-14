"""
DGSDK - Python wrapper for Delto Gripper SDK.
"""

__version__ = "2.0.0"

from .wrapper import DGSDK
from .types import (
    # Constants
    MAX_JOINT_COUNT,
    MAX_FINGER_COUNT,
    MAX_FINGER_JOINT_COUNT,
    CARTESIAN_COORDINATE_POSE_COUNT,
    MAX_RECEIVED_DATA_SIZE,
    MAX_GRIPPER_IP_ADDRESS_SIZE,
    MAX_GRIPPER_IP_BYTE_LENGTH,
    MAX_COMPORT_NAME_SIZE,
    MAX_BLEND_COUNT,
    MAX_BLEND_ADD_POSE_COUNT,
    MAX_RECIPE_POSE_COUNT,
    MAX_RECIPE_GAIN_COUNT,
    MAX_RECIPE_GRASP_COUNT,
    MAX_GRASP_OPTION_COUNT,
    MAX_GRIPPER_GPIO_SIZE,
    MAX_RECEIVED_DATA_TYPE_COUNT,
    MAX_BASE_JOINT_COUNT,
    PI,
    DEGREE_TO_RADIAN,
    RADIAN_TO_DEGREE,

    # Enums
    DGResult,
    DGModel,
    BlendMotionStatus,
    CommunicationMode,
    ControlMode,
    GainMode,
    DeveloperModeCommand,
    ReceivedDataType,
    DGGraspMode,
    DGGraspOption,
    DGDiagnosis,
    DGSensorType,

    # Structures
    ReceivedGripperData,
    RecipeBlendData,
    GripperSystemSetting,
    GripperSetting,
    RecipePoseData,
    RecipeGainData,
    RecipeGraspData,
    ReceivedFingertipSensorData,
    ReceivedGPIOData,
    DiagnosisSystem,

    # Callback Types
    ReceivedGripperDatasCallback,
    ConnectedToGripperCallback,
    DisconnectedToGripperCallback,
    CommunicationPeriodCallback,
    DiagnosisSystemCallback,
    ReceivedSensorCallback,
    ReceivedGPIOCallback,
    DataProcessingCallback,
)

__all__ = [
    # Main class
    "DGSDK",

    # Version
    "__version__",

    # Constants
    "MAX_JOINT_COUNT",
    "MAX_FINGER_COUNT",
    "MAX_FINGER_JOINT_COUNT",
    "CARTESIAN_COORDINATE_POSE_COUNT",
    "MAX_RECEIVED_DATA_SIZE",
    "MAX_GRIPPER_IP_ADDRESS_SIZE",
    "MAX_GRIPPER_IP_BYTE_LENGTH",
    "MAX_COMPORT_NAME_SIZE",
    "MAX_BLEND_COUNT",
    "MAX_BLEND_ADD_POSE_COUNT",
    "MAX_RECIPE_POSE_COUNT",
    "MAX_RECIPE_GAIN_COUNT",
    "MAX_RECIPE_GRASP_COUNT",
    "MAX_GRASP_OPTION_COUNT",
    "MAX_GRIPPER_GPIO_SIZE",
    "MAX_RECEIVED_DATA_TYPE_COUNT",
    "MAX_BASE_JOINT_COUNT",
    "PI",
    "DEGREE_TO_RADIAN",
    "RADIAN_TO_DEGREE",

    # Enums
    "DGResult",
    "DGModel",
    "BlendMotionStatus",
    "CommunicationMode",
    "ControlMode",
    "GainMode",
    "DeveloperModeCommand",
    "ReceivedDataType",
    "DGGraspMode",
    "DGGraspOption",
    "DGDiagnosis",
    "DGSensorType",

    # Structures
    "ReceivedGripperData",
    "RecipeBlendData",
    "GripperSystemSetting",
    "GripperSetting",
    "RecipePoseData",
    "RecipeGainData",
    "RecipeGraspData",
    "ReceivedFingertipSensorData",
    "ReceivedGPIOData",
    "DiagnosisSystem",

    # Callback Types
    "ReceivedGripperDatasCallback",
    "ConnectedToGripperCallback",
    "DisconnectedToGripperCallback",
    "CommunicationPeriodCallback",
    "DiagnosisSystemCallback",
    "ReceivedSensorCallback",
    "ReceivedGPIOCallback",
    "DataProcessingCallback",
]
