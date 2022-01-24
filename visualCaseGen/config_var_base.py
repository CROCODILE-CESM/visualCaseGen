import logging
from visualCaseGen.dummy_widget import DummyWidget
from visualCaseGen.OutHandler import handler as owh

from z3 import SeqRef, main_ctx, Z3_mk_const, to_symbol, StringSort
from z3 import And, Or, Not, Implies, is_not
from z3 import Solver, sat, unsat
from z3 import z3util

from traitlets import HasTraits, Any, default, validate, List

import cProfile, pstats
profiler = cProfile.Profile()

logger = logging.getLogger(__name__)

class Logic():
    """Container for logic data"""
    # assertions keeping track of variable assignments. key is varname, value is assignment assertion
    asrt_assignments = dict()
    # assertions for options lists of variables. key is varname, value is options assertion
    asrt_options = dict()
    # relational assertions. key is ASSERTION, value is ERRNAME.
    asrt_relationals = dict()
    # all variables that appear in one or more relational assertions
    all_relational_vars = set()

    @classmethod
    def reset(cls):
        cls.asrt_assignments = dict()
        cls.asrt_options = dict()
        cls.asrt_relationals = dict()
        cls.all_relational_vars = set()
    
    @classmethod
    def insert_relational_assertions(cls, assertions_setter, vdict):
        new_assertions = assertions_setter(vdict)
        # Check if any assertion has been provided multiple times.
        # If not, update the relational_assertions_dict to include new assertions (simplified).
        for asrt in new_assertions:
            if asrt in cls.asrt_relationals:
                raise ValueError("Versions of assertion encountered multiple times: {}".format(asrt))
        cls.asrt_relationals.update(new_assertions)

        for asrt in new_assertions:
            related_vars = {vdict[var.sexpr()] for var in z3util.get_vars(asrt)}
            cls.all_relational_vars.update(related_vars)
            for var in related_vars:
                var._related_vars.update(related_vars - {var})

        s = Solver()
        s.add(list(cls.asrt_assignments.values()))
        s.add(list(cls.asrt_options.values()))
        s.add(list(cls.asrt_relationals.keys()))
        if s.check() == unsat:
            raise RuntimeError("Relational assertions not satisfiable!")

    @classmethod
    def add_options(cls, var, new_opts):
        cls.asrt_options[var.name] = Or([var==opt for opt in new_opts])

    @classmethod
    def add_assignment(cls, var, new_value, check_sat=True):

        status = True
        err_msg = ''

        # first, pop the old assignment
        old_assignment = cls.asrt_assignments.pop(var.name, None)

        # check if new new_value is sat. if so, register the new assignment
        if new_value is not None:

            if check_sat:
                if var.has_options():
                    if new_value not in var.options:
                        status = False
                        err_msg = '{} not an option for {}'.format(new_value, var.name)

                if status is True:
                    # now, check if the value satisfies all assertions

                    # first add all assertions including the assignment being checked but excluding the relational
                    # assignments because we will pop the relational assertions if the solver is unsat
                    s = Solver()
                    s.add(list(cls.asrt_assignments.values()))
                    s.add(list(cls.asrt_options.values()))
                    s.add(var==new_value)

                    # now push and temporarily add relational assertions
                    s.push()
                    s.add(list(cls.asrt_relationals.keys()))

                    if s.check() == unsat:
                        s.pop()
                        for asrt in cls.asrt_relationals:
                            s.add(asrt)
                            if s.check() == unsat:
                                status = False
                                err_msg = '{}={} violates assertion:"{}"'.format(var.name,new_value,cls.asrt_relationals[asrt])
                                break

            if status is False:
                # reinsert old assignment and raise error
                if old_assignment is not None:
                    cls.asrt_assignments[var.name] = old_assignment
                raise AssertionError(err_msg)
            else:
                cls.asrt_assignments[var.name] = var==new_value
        
        cls._update_all_options_validities(var)

    @classmethod
    def get_options_validities(cls, var, s=None):
        if s is None:
            s = Solver()
            s.add(list(cls.asrt_options.values()))
            s.add(list(cls.asrt_relationals.keys()))
            s.add([cls.asrt_assignments[varname] for varname in cls.asrt_assignments.keys() if varname != var.name])
        return {opt: s.check(var==opt)==sat for opt in var._options}

    @classmethod
    def _update_all_options_validities(cls, invoker_var):
        """ When a variable value gets (re-)assigned, this method is called the refresh options validities of all
        other variables that may be affected."""
        logger.debug("Updating options validities of ALL relational variables")

        #profiler.enable()

        s = Solver()
        s.add(list(cls.asrt_options.values()))
        s.add(list(cls.asrt_relationals.keys())) 

        def __eval_new_validities_consequences(var):
            """ This version of __eval_new_validities uses z3.consequences, which is more expensive than the 
            below version, __eval_new_validities, so use that instead. Maybe there is a more efficient
            way to utilize z3.consequences, so I am keeping it here for now.""" 
            s.push()
            s.add([cls.asrt_assignments[varname] for varname in cls.asrt_assignments if varname != var.name ])
            checklist = [var==opt for opt in var.options]
            res = s.consequences([], checklist)
            assert res[0] == sat, "_update_all_options_validities called for an unsat assignment!"

            new_validities = {opt:True for opt in var.options}
            for implication in res[1]:
                consequent = implication.arg(1)
                if is_not(consequent):
                    invalid_val_str = consequent.arg(0).arg(1).as_string() #todo: generalize this for non-string vars
                    new_validities[invalid_val_str] = False
            s.pop()
            return new_validities

        def __eval_new_validities(var):
            s.push()
            s.add([logic.asrt_assignments[varname] for varname in logic.asrt_assignments if varname != var.name ])
            new_validities = {opt: s.check(var==opt)==sat for opt in var._options}
            s.pop()
            return new_validities

        # (ivar==1) First, evaluate if (re-)assignment of self has made an options validities change in its related variables.
        # (ivar>1) Then, recursively check the related variables of related variables whose options validities have changed.
        affected_vars = [invoker_var]+list(invoker_var._related_vars)
        ivar = 1
        while len(affected_vars)>ivar:
            var = affected_vars[ivar]
            if var.has_options():
                new_validities = __eval_new_validities(var)
                if new_validities != var._options_validities:
                    var._update_options(new_validities=new_validities)
                    affected_vars += [var_other for var_other in var._related_vars if var_other not in affected_vars]
            ivar += 1

        #profiler.disable()

    @classmethod
    def retrieve_error_msg(cls, var, value):
        """Given a failing assignment, retrieves the error message associated with the relational assertion
        leading to unsat."""

        s = Solver()
        s.add([logic.asrt_assignments[varname] for varname in logic.asrt_assignments.keys() if varname != var.name])
        s.add(list(logic.asrt_options.values()))

        # first, confirm the assignment is unsat
        if s.check( And( And(list(logic.asrt_relationals.keys())), var==value )) == sat:
            raise RuntimeError("_retrieve_error_msg method called for a satisfiable assignment")
        
        for asrt in logic.asrt_relationals:
            s.add(asrt)
            if s.check(var==value) == unsat:
                return '{}={} violates assertion:"{}"'.format(var.name, value, logic.asrt_relationals[asrt])

        return '{}={} violates multiple assertions.'.format(var.name, value)

logic = Logic()


class ConfigVarBase(SeqRef, HasTraits):
    
    # Dictionary of instances. This should not be modified or overriden in derived classes.
    vdict = {}
    
    # characters used in user interface to designate option validities
    invalid_opt_char = chr(int("274C",base=16))
    valid_opt_char = chr(int("2713",base=16))

    # Trait
    value = Any()

    def __init__(self, name, value=None, options=None, tooltips=(), ctx=None, always_set=False, widget_none_val=None):

        # Check if the variable has already been defined 
        if name in ConfigVarBase.vdict:
            raise RuntimeError("Attempted to re-define ConfigVarBase instance {}.".format(name))
        
        if ctx==None:
            ctx = main_ctx()

        # Instantiate the super class, i.e., a Z3 constant
        if isinstance(self.value, str):
            # Below instantiation mimics String() definition in z3.py
            super().__init__(Z3_mk_const(ctx.ref(), to_symbol(name, ctx), StringSort(ctx).ast), ctx)
        else:
            raise NotImplementedError

        # Initialize members
        self.name = name

        # Temporarily set private members options and value to None. These will be 
        # updated with special property setter below.
        self._options = None

        # Initialize all other private members
        self._options_validities = {}
        self._error_messages = []
        self._related_vars = set() # set of other variables sharing relational assertions with this var.
        self._always_set = always_set # if a ConfigVarBase instance with options, make sure a value is always set
        self._widget_none_val = widget_none_val
        self._widget = DummyWidget(value=widget_none_val)
        self._widget.tooltips = tooltips

        # Now call property setters of options and value
        if options is not None:
            self.options = options

        self.value = value

        # Record this newly created instance in the class member storing instances
        ConfigVarBase.vdict[name] = self
        logger.debug("ConfigVarBase %s created.", self.name)

    @staticmethod
    def reset():
        ConfigVarBase.vdict = dict()
        logic.reset()

    @staticmethod
    def exists(varname):
        """Check if a variable is already defined."""
        return varname in ConfigVarBase.vdict

    @classmethod
    def add_relational_assertions(cls, assertions_setter):
        logic.insert_relational_assertions(assertions_setter, cls.vdict)

    @default('value')
    def _default_value(self):
        return None

    @property
    def widget_none_val(self):
        return self._widget_none_val

    def is_none(self):
        return self.value is None

    @property
    def options(self):
        return self._options

    @options.setter
    def options(self, new_opts):
        logger.debug("Assigning the options of ConfigVarBase %s", self.name)
        assert isinstance(new_opts, (list,set))
        logic.add_options(self, new_opts)
        self._update_options(new_opts=new_opts)
    
    @property
    def tooltips(self):
        return self._widget.tooltips

    @tooltips.setter
    def tooltips(self, new_tooltips):
        self._widget.tooltips = new_tooltips

    def has_options(self):
        return self._options is not None

    def _update_options(self, new_validities=None, new_opts=None):
        """ This method updates options, validities, and displayed widget options.
        If needed, value is also updated according to the options update."""

        # check if validities are being updated only, while options remain the same
        validity_change_only = new_opts is None or new_opts == self._options
        old_widget_value = self._widget.value
        old_validities = self._options_validities

        if not validity_change_only:
            self._options = new_opts

        if new_validities is None:
            self._options_validities = logic.get_options_validities(self)
        else:
            self._options_validities = new_validities

        if validity_change_only and old_validities == self._options_validities:
            return # no change in options or validities
        
        self._widget.options = tuple(
            '{} {}'.format(self.valid_opt_char, opt) if self._options_validities[opt] \
            else '{} {}'.format(self.invalid_opt_char, opt) for opt in self._options)
        
        if validity_change_only:
            self._widget.value = old_widget_value 
        else:
           if self._always_set:
               self._set_to_first_valid_opt() 

    def _set_to_first_valid_opt(self):
        """ Set the value of the instance to the first option that is valid."""
        for opt in self._options:
            if self._options_validities[opt] == True:
                self.value = opt
                break

    @property
    def widget(self):
        raise RuntimeError("Cannot access widget property from outside the ConfigVar class")
    
    @widget.setter
    def widget(self, new_widget):
        old_widget = self._widget
        self._widget = new_widget
        if self.has_options():
            self._widget.options = old_widget.options
        self._widget.value = old_widget.value
        self._widget.tooltips = old_widget.tooltips

        # unobserve old widget frontend
        old_widget.unobserve(
            self._process_frontend_value_change,
            names='_property_lock',
            type='change'
        )

        # observe new widget frontend
        self._widget.observe(
            self._process_frontend_value_change,
            names='_property_lock', # instead of 'value', use '_property_lock' to capture frontend changes only
            type='change'
        )

    def set_widget_properties(self, property_dict):
        assert isinstance(property_dict, dict)
        for key, val in property_dict.items():
            assert key != "options", "Must set widget options via .options setter"
            assert key != "value", "Must set widget value via .value setter"
            setattr(self._widget, key, val)

    @property
    def widget_style(self):
        return self._widget.style

    @widget_style.setter
    def widget_style(self, style):
        self._widget.style = style

    @property
    def widget_layout(self):
        return self._widget.layout

    @widget_layout.setter
    def widget_layout(self, layout):
        self._widget.layout = layout

    @property
    def description(self):
        return self._widget.description
   
    @validate('value')
    def _validate_value(self, proposal):
        raise NotImplementedError("This method must be implemented in the derived class")

    @owh.out.capture()
    def _process_frontend_value_change(self, change):
        raise NotImplementedError("This method must be implemented in the derived class")
