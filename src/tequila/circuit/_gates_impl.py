import typing
import copy
import numbers
from abc import ABC
from tequila import TequilaException
from tequila.objective.objective import Variable, FixedVariable, assign_variable,Objective,VectorObjective
from tequila.hamiltonian import PauliString, QubitHamiltonian, paulis
from tequila.tools import list_assignment

from dataclasses import dataclass

# typing convenience shortcuts
UnionList = typing.Union[typing.Iterable[numbers.Integral], numbers.Integral]
UnionParam = typing.Union[Variable, FixedVariable]


class QGateImpl:

    @property
    def name(self):
        return self._name

    @property
    def target(self):
        return self._target

    @property
    def control(self):
        return self._control

    @property
    def qubits(self):
        return self._qubits

    @property
    def max_qubit(self):
        return self._max_qubit

    def extract_variables(self):
        return []

    def is_parametrized(self) -> bool:
        return hasattr(self, "parameter")

    def make_generator(self, include_controls=False):
        if self.generator and include_controls and self.is_controlled():
            return paulis.Qm(self.control) * self.generator

        return self.generator

    def __init__(self, name, target: UnionList, control: UnionList = None, generator: QubitHamiltonian = None):
        self._name = name
        self._target = tuple(list_assignment(target))
        self._control = tuple(list_assignment(control))
        self.finalize()
        # Set the active qubits
        if self.control:
            self._qubits = self.target + self.control
        else:
            self._qubits = self.target
        self._qubits = sorted(tuple(set(self._qubits)))
        self._max_qubit = self.compute_max_qubit()
        self.generator = generator

    def copy(self):
        return copy.deepcopy(self)

    def dagger(self):
        """
        :return: return the hermitian conjugate of the gate.
        """

        return QGateImpl(name=copy.copy(self.name), target=self.target,
                         control=self.control)

    def is_controlled(self) -> bool:
        """
        :return: True if the gate is controlled
        """
        if len(self.control) == 0:
            return False
        else:
            return True

    def is_single_qubit_gate(self) -> bool:
        """
        Convenience and easier to interpret
        :return: True if the Gate only acts on one qubit (not controlled)
        """
        return (not self.control) and (len(self.target) == 1)

    def finalize(self):
        if not self.target:
            raise Exception('Received no targets upon initialization')
        if self.is_controlled():
            for c in self.target:
                if c in self.control:
                    raise Exception("control and target are the same qubit: " + self.__str__())

    def __str__(self):
        result = str(self.name) + "(target=" + str(self.target)
        if not self.is_single_qubit_gate():
            result += ", control=" + str(self.control)
        result += ")"
        return result

    def __repr__(self):
        """
        Todo: Add Nice stringification
        """
        return self.__str__()

    def compute_max_qubit(self):
        """
        :return: highest qubit index used by this gate
        """
        if self.control is None:
            return max(self.target)
        else:
            return max(self.target + self.control)

    def __eq__(self, other):
        if self.name != other.name:
            return False
        if self.target != other.target:
            return False
        if self.control != other.control:
            return False
        return True

    def map_qubits(self, qubit_map: dict):
        mapped = copy.deepcopy(self)
        mapped._target = tuple([qubit_map[i] for i in self.target])
        qubits = mapped._target
        if self.control is not None:
            mapped._control = tuple([qubit_map[i] for i in self.control])
            qubits += mapped._control
        mapped._qubits = sorted(tuple(set(qubits)))
        mapped._max_qubit = mapped.compute_max_qubit()
        if self.generator:
            mapped.generator = self.generator.map_qubits(qubit_map)
        mapped.finalize()
        return mapped

class ParametrizedGateImpl(QGateImpl, ABC):
    '''
    the base class from which all parametrized gates inherit. User defined gates, when implemented, are liable to be members of this class directly.
    '''

    def extract_variables(self):
        if hasattr(self.parameter, "extract_variables"):
            return self.parameter.extract_variables()
        else:
            return []

    def dagger(self):
        raise TequilaException("should not be called from ABC")

    @property
    def parameter(self):
        return self._parameter

    @parameter.setter
    def parameter(self, other):
        self.parameter = assign_variable(variable=other)

    def __init__(self, name, parameter: UnionParam, target: UnionList, control: UnionList = None,
                generator: QubitHamiltonian = None):
        super().__init__(name=name, target=target, control=control, generator=generator)
        if isinstance(parameter, VectorObjective):
            raise TequilaException('Received VectorObjective {} as parameter. This is forbidden.'.format(parameter))
        self._parameter = assign_variable(variable=parameter)

    def __str__(self):
        result = str(self.name) + "(target=" + str(self.target)
        if not self.is_single_qubit_gate():
            result += ", control=" + str(self.control)

        result += ", parameter=" + str(self._parameter)
        result += ")"
        return result

    def __eq__(self, other):
        if not isinstance(other, ParametrizedGateImpl):
            return False
        if not super().__eq__(other):
            return False
        if self._parameter != other._parameter:
            return False
        return True

class DifferentiableGateImpl(ParametrizedGateImpl):

    @property
    def eigenvalues_magnitude(self):
        return self._eigenvalues_magnitude

    def __init__(self,eigenvalues_magnitude, *args, **kwargs):
        self._eigenvalues_magnitude=eigenvalues_magnitude
        super().__init__(*args, **kwargs)

class RotationGateImpl(DifferentiableGateImpl):
    axis_to_string = {0: "x", 1: "y", 2: "z"}
    string_to_axis = {"x": 0, "y": 1, "z": 2}

    @staticmethod
    def get_name(axis):
        axis = RotationGateImpl.assign_axis(axis)
        return "R" + RotationGateImpl.axis_to_string[axis]

    @property
    def axis(self):
        return self._axis

    @axis.setter
    def axis(self, value):
        self._axis = self.assign_axis(value)

    def __ipow__(self, power, modulo=None):
        self.parameter *= power
        return self

    def __pow__(self, power, modulo=None):
        result = copy.deepcopy(self)
        result.parameter *= power
        return result

    def __init__(self, axis, angle, target: list, control: list = None):
        assert (angle is not None)
        super().__init__(eigenvalues_magnitude=0.5, name=self.get_name(axis=axis), parameter=angle, target=target, control=control)
        self._axis = self.assign_axis(axis)
        self.generator = self.assign_generator(self.axis, self.target)

    @staticmethod
    def assign_axis(axis):
        if axis in RotationGateImpl.string_to_axis:
            return RotationGateImpl.string_to_axis[axis]
        elif hasattr(axis, "lower") and axis.lower() in RotationGateImpl.string_to_axis:
            return RotationGateImpl.string_to_axis[axis.lower()]
        else:
            assert (axis in [0, 1, 2])
            return axis

    @staticmethod
    def assign_generator(axis, qubits):
        if axis == 0:
            return sum(paulis.X(q) for q in qubits)
        if axis == 1:
            return sum(paulis.Y(q) for q in qubits)

        return sum(paulis.Z(q) for q in qubits)

    def dagger(self):
        result = copy.deepcopy(self)
        result._parameter = assign_variable(-self.parameter)
        return result


class PhaseGateImpl(DifferentiableGateImpl):

    def __init__(self, phase, target: list, control: list = None):
        assert (phase is not None)
        super().__init__(eigenvalues_magnitude=0.5, name='Phase', parameter=phase, target=target, control=control)
        self.generator = paulis.Z(target) - paulis.I(target)

    def dagger(self):
        result = copy.deepcopy(self)
        result._parameter = -self.parameter
        return result

    def __pow__(self, power, modulo=None):
        result = copy.deepcopy(self)
        result.parameter *= power
        return result


class PowerGateImpl(ParametrizedGateImpl):

    def __init__(self, name, target: list, power=None, control: list = None, generator: QubitHamiltonian = None):
        super().__init__(name=name, parameter=power, target=target, control=control, generator=generator)

    def dagger(self):
        result = copy.deepcopy(self)
        return result

class GeneralizedRotationImpl(DifferentiableGateImpl):
    """
    A gate which behaves like a generalized rotation
     - its generator only has two distinguishable eigenvalues
     - it is then differentiable by the shift rule
     - shift needs to be given upon initialization (otherwise its default is 1/2)
     - the generator will not be verified to fullfill the properties
     Compiling will be done in analogy to a trotterized gate with steps=1 as default

    The gate will act in the same way as rotations and exppauli gates
    exp(-i angle/2 generator)
    """

    @staticmethod
    def extract_targets(generator):
        targets = []
        for ps in generator.paulistrings:
            targets += [k for k in ps.keys()]
        return tuple(set(targets))

    def __init__(self, angle, generator, control=None, eigenvalues_magnitude=0.5, steps=1):
        super().__init__(eigenvalues_magnitude=eigenvalues_magnitude, name="GenRot", parameter=angle, target=self.extract_targets(generator), control=control)
        self.steps = steps
        self.generator = generator

    def dagger(self):
        result = copy.deepcopy(self)
        result._parameter = assign_variable(-self.parameter)
        return result


class ExponentialPauliGateImpl(DifferentiableGateImpl):
    """
    Same convention as for rotation gates:
    Exp(-i angle/2 * paulistring)
    """

    def dagger(self):
        result = copy.deepcopy(self)
        result._parameter = -self.parameter
        return result

    def __init__(self, paulistring: PauliString, angle: float, control: typing.List[int] = None):
        super().__init__(eigenvalues_magnitude=0.5, name="Exp-Pauli", target=tuple(t for t in paulistring.keys()), control=control, parameter=angle)
        self.paulistring = paulistring
        self.generator = QubitHamiltonian.from_paulistrings(paulistring)
        self.finalize()

    def __str__(self):
        result = str(self.name) + "(target=" + str(self.target)
        if not self.is_single_qubit_gate():
            result += ", control=" + str(self.control)

        result += ", parameter=" + str(self._parameter)
        result += ", paulistring=" + str(self.paulistring)
        result += ")"
        return result

    def map_qubits(self, qubit_map: dict):
        mapped = super().map_qubits(qubit_map=qubit_map)
        mapped.paulistring = self.paulistring.map_qubits(qubit_map)
        return mapped

@dataclass
class TrotterParameters:
    threshold: float = 0.0
    join_components: bool = True
    randomize_component_order: bool = False
    randomize: bool = False


class TrotterizedGateImpl(QGateImpl):

    def is_parametrized(self) -> bool:
        return True

    def extract_variables(self) -> typing.Dict[str, numbers.Number]:
        tmp = []
        for angle in self.angles:
            if hasattr(angle, "extract_variables"):
                tmp += angle.extract_variables()
        return list(set(tmp))

    @property
    def angles(self):
        return self._parameter

    @angles.setter
    def angles(self, other):
        self._parameter = other

    def __init__(self, generators: typing.Union[QubitHamiltonian, typing.List[QubitHamiltonian]],
                 steps: int = 1,
                 angles: typing.Union[list, numbers.Real, Variable] = None,
                 control: typing.Union[list, int] = None,
                 threshold: numbers.Real = 0.0,
                 join_components: bool = True,
                 randomize_component_order: bool = True,
                 randomize: bool = True):
        """
        :param generators: list of generators
        :param angles: coefficients for each generator
        :param steps: Trotter Steps
        :param control: control qubits
        :param threshold: neglect terms in the given Hamiltonians if their coefficients are below this threshold
        :param join_components: The generators are trotterized together. If False the first generator is trotterized, then the second etc
        Note that for steps==1 as well as len(generators)==1 this has no effect
        :param randomize_component_order: randomize the order in the generators order before trotterizing
        :param randomize: randomize the trotter decomposition of each generator
        """
        super().__init__(name="Trotterized", target=self.extract_targets(generators), control=control)
        self.generators = list_assignment(generators)
        self.angles = angles
        self.steps = steps
        self.threshold = threshold
        self.join_components = join_components
        self.randomize_component_order = randomize_component_order
        self.randomize = randomize
        self.finalize()

    def __str__(self):
        result = str(self.name) + "(target=" + str(self.target)
        if not self.is_single_qubit_gate():
            result += ", control=" + str(self.control)

        result += ", angles=" + str(self._parameter)
        result += ", generators=" + str(self.generators)
        result += ")"
        return result

    @staticmethod
    def extract_targets(generators):
        targets = []
        for g in generators:
            for ps in g.paulistrings:
                targets += [k for k in ps.keys()]
        return tuple(set(targets))

    def dagger(self):
        result = copy.deepcopy(self)
        angles = []
        for angle in self.angles:
            angles.append(-angle)
        result.angles = angles
        return result

    def map_qubits(self, qubit_map: dict):
        mapped = super().map_qubits(qubit_map=qubit_map)
        mapped.generators = [generator.map_qubits(qubit_map=qubit_map) for generator in mapped.generators]
        return mapped
