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

"""Tests for reactor blueprints."""
import unittest
import os

from armi.reactor import blueprints
from armi import settings
from armi.reactor import reactors
from armi.reactor.blueprints import reactorBlueprint
from armi.reactor.blueprints.tests import test_customIsotopics

CORE_BLUEPRINT = """
core:
  lattice file: {0}geometry.xml
  origin:
    x: 0.0
    y: 10.1
    z: 1.1
sfp:
    lattice file: {0}sfp-geom.xml
    lattice pitch:
        x: 25.0
        y: 25.0
    origin:
        x: 0.0
        y: 12.1
        z: 1.1
"""

GEOM = """<?xml version="1.0" ?>
<reactor geom="hex" symmetry="third core periodic">
    <assembly name="IC" pos="1" ring="1"/>
    <assembly name="IC" pos="2" ring="2"/>
</reactor>
"""


class TestReactorBlueprints(unittest.TestCase):
    """Tests for reactor blueprints."""

    def setUp(self):
        # add testMethodName to avoid I/O collisions during parallel testing
        self.systemDesigns = reactorBlueprint.Systems.load(
            CORE_BLUEPRINT.format(self._testMethodName)
        )

    def test_simple_read(self):
        self.assertEqual(
            self.systemDesigns["core"].latticeFile,
            self._testMethodName + "geometry.xml",
        )
        self.assertEqual(
            self.systemDesigns["sfp"].latticeFile, self._testMethodName + "sfp-geom.xml"
        )
        self.assertAlmostEqual(self.systemDesigns["sfp"].origin.y, 12.1)

    def _setupReactor(self):
        fnames = [self._testMethodName + n for n in ["geometry.xml", "sfp-geom.xml"]]
        for fn in fnames:
            with open(fn, "w") as f:
                f.write(GEOM)
        cs = settings.Settings()
        cs["geomFile"] = self._testMethodName + "geometry.xml"
        bp = blueprints.Blueprints.load(
            test_customIsotopics.TestCustomIsotopics.yamlString
        )
        bp.systemDesigns = self.systemDesigns
        reactor = reactors.Reactor(cs, bp)
        core = bp.systemDesigns["core"].construct(cs, bp, reactor)
        sfp = bp.systemDesigns["sfp"].construct(cs, bp, reactor)
        for fn in fnames:
            os.remove(fn)
        return core, sfp

    def test_construct(self):
        """Actually construct some reactor systems."""
        core, sfp = self._setupReactor()
        self.assertEqual(len(core), 2)
        self.assertEqual(len(sfp), 2)

    def test_materialDataSummary(self):
        """Test that the material data summary for the core is valid as a printout to the stdout."""
        expectedMaterialData = [
            ("Custom Material", "ARMI", False),
            ("HT9", "ARMI", False),
            ("UZr", "ARMI", False),
        ]
        core, _sfp = self._setupReactor()
        materialData = reactorBlueprint.summarizeMaterialData(core)
        for actual, expected in zip(materialData, expectedMaterialData):
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
