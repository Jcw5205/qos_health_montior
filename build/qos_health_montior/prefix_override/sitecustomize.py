import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/jacobb/ros2_ws/qos_health_montior/install/qos_health_montior'
