"""Network-free tests: never touch Portainer, GitHub, or operational music files."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import service


COMPOSE = """services:
  music-tag-filler:
    image: music-tag-filler-nas:github-1234
    environment:
      MA_API_TOKEN: keep-this-secret
      TZ: Asia/Seoul
    ports:
      - "8000:8000"
    volumes:
      - type: bind
        source: /volume1/Multimedia/Music
        target: /music
        read_only: false
      - type: bind
        source: /volume3/docker3/music-tag-filler-v6/data
        target: /data
"""
NEW_IMAGE = "ghcr.io/sooncheol/music-tag-filler-nas:sha-" + ("a" * 40)
CFG = {
    "id": "music-tag-filler", "repo": "SoonCheol/music-tag-filler-nas",
    "workflow": "build-image.yml", "branch": "master",
    "image_repo": "ghcr.io/sooncheol/music-tag-filler-nas",
    "legacy_images": ["music-tag-filler-nas"],
    "stack_id": 32, "endpoint_id": 7, "stack": "music-tag-filler",
    "service": "music-tag-filler",
    "safety_url": "http://music-tag-filler:8000/api/updater/safety"
}
STACK = {"Id": 32, "EndpointId": 7, "Name": "music-tag-filler", "Type": 2,
         "Env": [{"name": "MA_API_TOKEN", "value": "keep-this-secret"}]}


class UpdateAgentSafetyTests(unittest.TestCase):
    def test_image_only_compose_change(self):
        original = service.yaml.safe_load(COMPOSE)
        updated = service.patched_stack(COMPOSE, original, "music-tag-filler", NEW_IMAGE)
        expected = copy.deepcopy(original)
        expected["services"]["music-tag-filler"]["image"] = NEW_IMAGE
        self.assertEqual(service.yaml.safe_load(updated), expected)
        self.assertIn("read_only: false", updated)
        self.assertIn("MA_API_TOKEN: keep-this-secret", updated)

    def test_duplicate_image_line_blocks_update(self):
        raw = COMPOSE.replace("    environment:", "    image: music-tag-filler-nas:github-1234\n    environment:")
        with self.assertRaises(RuntimeError):
            service.patched_stack(raw, service.yaml.safe_load(COMPOSE), "music-tag-filler", NEW_IMAGE)

    def test_allowlist_accepts_valid_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            path.write_text(json.dumps({"apps": [CFG]}), encoding="utf-8")
            self.assertEqual(service.load_apps(path)["music-tag-filler"], CFG)
            bad = dict(CFG, image_repo="bad;something")
            path.write_text(json.dumps({"apps": [bad]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                service.load_apps(path)

    def test_missing_secret_does_not_authenticate(self):
        self.assertFalse(service.equal("", ""))
        self.assertFalse(service.equal("", "configured"))
        self.assertFalse(service.equal("wrong", "configured"))
        self.assertTrue(service.equal("same", "same"))

    def test_wrong_portainer_stack_refused(self):
        with patch.object(service, "portainer", return_value={**STACK, "EndpointId": 9}) as stub:
            with self.assertRaises(RuntimeError):
                service.current_stack(CFG)
            self.assertEqual(stub.call_count, 1)

    def test_multi_service_stack_refused(self):
        extra = COMPOSE + "  other:\n    image: alpine:3\n"
        def fake_request(_method, url, _body=None):
            return STACK if url == "/stacks/32" else {"StackFileContent": extra}
        with patch.object(service, "portainer", side_effect=fake_request):
            with self.assertRaises(RuntimeError):
                service.current_stack(CFG)

    def test_busy_app_prevents_any_mutation(self):
        service.task = {"app_id": CFG["id"], "state": "queued"}
        with patch.object(service, "safety_check", side_effect=RuntimeError("busy")):
            with patch.object(service, "portainer") as client:
                service.worker(CFG, "music-tag-filler-nas:github-1234", NEW_IMAGE)
                client.assert_not_called()
        self.assertEqual(service.task["state"], "failed")

    def test_update_preserves_environment_and_creates_private_snapshot(self):
        stack_file = [COMPOSE]
        sent = []
        def fake_portainer(method, path, body=None):
            if method == "GET" and path.endswith("/file"):
                return {"StackFileContent": stack_file[0]}
            if method == "GET":
                return STACK
            sent.append(body)
            stack_file[0] = body["StackFileContent"]
            return {}
        service.task = {"app_id": CFG["id"], "state": "queued"}
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"UPDATER_STATE_DIR": directory}):
                with patch.object(service, "portainer", side_effect=fake_portainer):
                    with patch.object(service, "safety_check", return_value=None):
                        service.worker(CFG, "music-tag-filler-nas:github-1234", NEW_IMAGE)
            snapshots = list(Path(directory).glob("*.json"))
            self.assertEqual(len(snapshots), 1)
            backup = json.loads(snapshots[0].read_text(encoding="utf-8"))
            self.assertEqual(backup["before"], "music-tag-filler-nas:github-1234")
            self.assertEqual(backup["compose"], COMPOSE)
            self.assertEqual(backup["env"], STACK["Env"])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["Env"], STACK["Env"])
        self.assertFalse(sent[0]["Prune"])
        self.assertEqual(service.task["state"], "done")
        self.assertEqual(service.yaml.safe_load(stack_file[0])["services"]["music-tag-filler"]["image"], NEW_IMAGE)


if __name__ == "__main__":
    unittest.main()
