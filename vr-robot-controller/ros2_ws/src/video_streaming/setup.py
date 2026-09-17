from setuptools import find_packages, setup

package_name = 'video_streaming'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Wesley Burcham',
    maintainer_email='burchamw@merrimack.edu',
    description='CSI camera capture + WebRTC/RTSP publisher',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'camera_publisher_node = video_streaming.camera_publisher_node:main',
        ],
    },
)
