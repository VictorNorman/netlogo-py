"""The `engine` package. `engine.netlogo` is the only module in it now --
see its own docstring for the free-function, class-less NetLogo-flavored
runtime every model file (models/*.py) is built against.

(This package used to also hold an OOP engine, core.py, and a vectorized
NumPy engine, vector_core.py/vector_turtles.py/nl.py -- both were removed
once every model had been ported onto engine.netlogo, leaving nothing
importing them.)
"""
