
from setuptools import setup, find_packages

package_name = 'qos_health_montior'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ryanhorenci',
    maintainer_email='ryanhorenci@todo.todo',
    description='ROS2 QoS Health Monitor Node',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
    'console_scripts': [
        'qos_health_node = qos_health_montior.qos_health_node:main',
    ],
}

)

