import unittest

from MayaScope.analysis.graph import QueryCancelled
from MayaScope.analysis.identity import build_host_identity_index
from MayaScope.model import SceneNode, SceneSnapshot


class HostIdentityIndexTests(unittest.TestCase):
    def test_exact_paths_survive_while_ambiguous_short_names_are_omitted(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("a", "ctrl", "transform", dag_paths=("|rigA|ctrl",)),
                SceneNode("b", "ctrl", "transform", dag_paths=("|rigB|ctrl",)),
                SceneNode("c", "material", "lambert"),
            ),
            (),
        )
        index = build_host_identity_index(snapshot)
        self.assertNotIn("ctrl", index)
        self.assertEqual(index["|rigA|ctrl"], "a")
        self.assertEqual(index["|rigB|ctrl"], "b")
        self.assertEqual(index["material"], "c")
        with self.assertRaises(TypeError):
            index["new"] = "node"

    def test_background_build_honors_cancellation(self):
        snapshot = SceneSnapshot.build(
            tuple(SceneNode(str(i), "node_%s" % i, "network") for i in range(5000)),
            (),
        )
        calls = {"count": 0}

        def cancelled():
            calls["count"] += 1
            return calls["count"] >= 2

        with self.assertRaises(QueryCancelled):
            build_host_identity_index(snapshot, cancelled=cancelled)


if __name__ == "__main__":
    unittest.main()
