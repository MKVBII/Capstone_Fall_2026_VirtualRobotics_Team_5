from setuptools import find_packages, setup

package_name = 'adapter_osoyoo_car'

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
    description='OSOYOO Pi Car robot adapter (first robot target)',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'osoyoo_car_adapter_node = adapter_osoyoo_car.osoyoo_car_adapter_node:main',
        ],
    },
)
