std_msgs/Header header
string data
<build_depend>std_msgs</build_depend>
<build_depend>rosidl_default_generators</build_depend>

<exec_depend>std_msgs</exec_depend>
<exec_depend>rosidl_default_runtime</exec_depend>
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/HeaderString.msg"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
