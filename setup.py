from setuptools import setup
try:
    from urllib import request
except ImportError:
    import urllib2 as request

fastep = request.urlopen('https://raw.githubusercontent.com/ninjaaron/fast-entry_points/master/fastentrypoints.py')
namespace = {}
exec(fastep.read(), namespace)

setup(
    name='wrld',
    version='0.2',
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
