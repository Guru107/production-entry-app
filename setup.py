from setuptools import find_packages, setup

setup(
	name="production_entry_app",
	version="0.0.1",
	description="An erpnext module to simplify production entries",
	author="Gurudatt Kulkarni",
	author_email="connect@gurudatt.in",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
)
