# Copyright 2019 TerraPower, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This module defines the ARMI input for a component definition, and code for constructing an ARMI ``Component``.

Special logic is required for handling component links.
"""
import six
import yamlize

from armi import runLog
from armi import materials
from armi.reactor import components
from armi.reactor.flags import Flags
from armi.utils import densityTools
from armi.localization import exceptions
from armi.nucDirectory import nuclideBases


class ComponentDimension(yamlize.Object):
    """
    Dummy object for ensuring well-formed component links are specified within the YAML input.

    This can be either a number (float or int), or a conformation string (``name.dimension``).
    """

    def __init__(self, value):
        # note: yamlizable does not call an __init__ method, instead it uses __new__ and setattr
        self.value = value
        if isinstance(value, six.string_types):
            if not components.COMPONENT_LINK_REGEX.search(value):
                raise ValueError(
                    "Bad component link `{}`, must be in form `name.dimension`".format(
                        value
                    )
                )

    def __repr__(self):
        return "<ComponentDimension value: {}>".format(self.value)

    @classmethod
    def from_yaml(cls, loader, node, _rtd=None):
        """
        Override the ``Yamlizable.from_yaml`` to inject custom interpretation of component dimension.

        This allows us to create a new object with either a string or numeric value.
        """
        try:
            val = loader.construct_object(node)
            self = ComponentDimension(val)
            loader.constructed_objects[node] = self
            return self
        except ValueError as ve:
            raise yamlize.YamlizingError(str(ve), node)

    @classmethod
    def to_yaml(cls, dumper, self, _rtd=None):
        """
        Override the ``Yamlizable.to_yaml`` to remove the object-like behavior, otherwise we'd end up with a
        ``{value: ...}`` dictionary.

        This allows someone to programmatically edit the component dimensions without using the ``ComponentDimension``
        class.
        """
        if not isinstance(self, cls):
            self = cls(self)
        node = dumper.represent_data(self.value)
        dumper.represented_objects[self] = node
        return node

    def __mul__(self, other):
        return self.value * other

    def __add__(self, other):
        return self.value + other

    def __div__(self, other):
        return self.value / other

    def __sub__(self, other):
        return self.value - other

    def __eq__(self, other):
        return self.value == other

    def __ne__(self, other):
        return self.value != other

    def __gt__(self, other):
        return self.value > other

    def __ge__(self, other):
        return self.value >= other

    def __lt__(self, other):
        return self.value < other

    def __le__(self, other):
        return self.value <= other

    def __hash__(self):
        return id(self)


class ComponentBlueprint(yamlize.Object):
    """
    This class defines the inputs necessary to build ARMI component objects. It uses ``yamlize`` to enable serialization
    to and from YAML.
    """

    name = yamlize.Attribute(type=str)

    @name.validator
    def name(self, name):  # pylint: disable=no-self-use; reason=yamlize requirement
        if name in {"cladding"}:
            raise ValueError("Cannot set ComponentBlueprint.name to {}".format(name))

    shape = yamlize.Attribute(type=str)

    @shape.validator
    def shape(self, shape):  # pylint: disable=no-self-use; reason=yamlize requirement
        normalizedShape = shape.strip().lower()
        if normalizedShape not in components.ComponentType.TYPES:
            raise ValueError("Cannot set ComponentBlueprint.shape to {}".format(shape))

    material = yamlize.Attribute(type=str)
    Tinput = yamlize.Attribute(type=float)
    Thot = yamlize.Attribute(type=float)
    isotopics = yamlize.Attribute(type=str, default=None)
    centers = yamlize.Attribute(type=str, default=None)
    orientation = yamlize.Attribute(type=str, default=None)
    mergeWith = yamlize.Attribute(type=str, default=None)

    def construct(self, blueprint, matMods):
        """Construct a component"""
        runLog.debug("Constructing component {}".format(self.name))
        kwargs, appliedMatMods = self._conformKwargs(blueprint, matMods)
        component = components.factory(self.shape.strip().lower(), [], kwargs)
        _insertDepletableNuclideKeys(component, blueprint)
        return component, appliedMatMods

    def _conformKwargs(self, blueprint, matMods):
        """This method gets the relevant kwargs to construct the component"""
        kwargs = {"mergeWith": self.mergeWith or "", "isotopics": self.isotopics or ""}

        for attr in self.attributes:  # yamlize magic
            val = attr.get_value(self)

            if attr.name == "shape" or val == attr.default:
                continue
            elif attr.name == "material":
                # value is a material instance
                value, appliedMatMods = self._constructMaterial(blueprint, matMods)
            else:
                value = attr.get_value(self)

            # Keep digging until the actual value is found. This is a bit of a hack to get around an
            # issue in yamlize/ComponentDimension where Dimensions can end up chained.
            while isinstance(value, ComponentDimension):
                value = value.value

            kwargs[attr.name] = value

        return kwargs, appliedMatMods

    def _constructMaterial(self, blueprint, matMods):
        nucsInProblem = blueprint.allNuclidesInProblem
        mat = materials.resolveMaterialClassByName(
            self.material
        )()  # make material with defaults

        if self.isotopics is not None:
            blueprint.customIsotopics.apply(mat, self.isotopics)

        appliedMatMods = False
        if any(matMods):
            try:
                mat.applyInputParams(
                    **matMods
                )  # update material with updated input params from YAML file.
                appliedMatMods = True
            except TypeError:
                # This component does not accept material modification inputs of the names passed in
                # Keep going since the modification could work for another component
                pass

        # expand elementals
        densityTools.expandElementalMassFracsToNuclides(
            mat.p.massFrac, blueprint.elementsToExpand
        )

        missing = set(mat.p.massFrac.keys()).difference(nucsInProblem)

        if missing:
            raise exceptions.ConsistencyError(
                "The nuclides {} are present in material {} by compositions, but are not "
                "specified in the input file. They need to be added.".format(
                    missing, mat
                )
            )

        return mat, appliedMatMods


def _insertDepletableNuclideKeys(c, blueprint):
    if not any(nuc in blueprint.activeNuclides for nuc in c.getNuclides()):
        return
    c.p.flags |= Flags.DEPLETABLE
    nuclideBases.initReachableActiveNuclidesThroughBurnChain(
        c.p.numberDensities, blueprint.activeNuclides
    )


# This import-time magic requires all possible components
# be imported before this module imports. The intent
# was to make registration basically automatic. This has proven
# to be quite problematic and will be replaced with an
# explicit plugin-level component registration system.
for dimName in set(
    [
        kw
        for cType in components.ComponentType.TYPES.values()
        for kw in cType.DIMENSION_NAMES
    ]
):
    setattr(
        ComponentBlueprint,
        dimName,
        yamlize.Attribute(name=dimName, type=ComponentDimension, default=None),
    )
