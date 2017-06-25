from setuptools import setup
import fastentrypoints

setup(
    name='wrld',
    version='0.7',
    author='Aaron Christianson',
    license='BSD',
    author_email='ninjaaron@gmail.com',
    url='https://github.com/ninjaaron/wrld',
    description='simplified bash loops (or, xargs -I on steroids)',
    long_description=open('README.rst').read(),
    keywords='evaluate',
    py_modules=['wrld'],
    entry_points={'console_scripts': ['wrld=wrld:main']},
)
