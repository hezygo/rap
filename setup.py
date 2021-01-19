import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()


with open("requirements.txt") as f:
    requirements = [l for l in f.read().splitlines() if l]


setuptools.setup(
    name="rap",
    version="0.5.3.5",
    author="so1n",
    author_email="so1n897046026@gmail.com",
    description="rap(par[::-1]) is advanced and fast python async rpc",
    install_requires=requirements,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/so1n/rap",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
)
