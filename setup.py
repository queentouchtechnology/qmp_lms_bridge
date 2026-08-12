from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

from qmp_lms_bridge import __version__ as version

setup(
    name="qmp_lms_bridge",
    version=version,
    description=(
        "Registers QMP LMS as a product on the QTT SaaS Platform — tenant "
        "scoping (Custom Fields), usage resolvers, cross-tenant reference "
        "validation, and hook-only doctype permission handlers. Touches "
        "no `lms` source file; qtt_platform stays fully product-agnostic. "
        "This app is the only place LMS-specific and platform-specific "
        "code are allowed to meet."
    ),
    author="Queen Touch Technology",
    author_email="queentouchtech@gmail.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
