# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=2,<3", "scipy>=1.15,<2"]
# ///
"""Offline grip candidates and measured-skin checks; never writes Unity assets."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation as R


def array(value, shape=None):
    a = np.asarray(value, dtype=float)
    if not np.isfinite(a).all() or (shape is not None and a.shape != shape):
        raise ValueError(f"Expected finite array of shape {shape}, got {a.shape}")
    return a


def points(value):
    a = array(value)
    if a.ndim != 2 or a.shape[1] != 3 or len(a) == 0:
        raise ValueError("Expected nonempty Nx3 points")
    return a


def rotation(value):
    q = array(value, (4,))
    if np.linalg.norm(q) < 1e-8:
        raise ValueError("Zero quaternion")
    return R.from_quat(q)


def convention(d):
    if d.get("coordinate_space") != "weapon-meters-xyzw":
        raise ValueError("Declare coordinate_space=weapon-meters-xyzw")


def offset(d, maximum):
    convention(d)
    if not np.isfinite(maximum) or maximum <= 0:
        raise ValueError("max-position-m must be positive")
    base_p = array(d["cached"]["position"], (3,))
    base_r = rotation(d["cached"]["rotation"])
    target_p = array(d["desired"]["position"], (3,))
    target_r = rotation(d["desired"]["rotation"])
    p, r = target_p - base_p, base_r.inv() * target_r
    if np.linalg.norm(p) > maximum:
        raise ValueError("Offset exceeds declared range; check sampling/frame/units before applying")
    return {"position": p.tolist(), "rotation": r.as_quat().tolist(), "scale": [1, 1, 1],
            "position_unit": "meters", "quaternion_order": "xyzw",
            "rotation_roundtrip_error_deg": float((target_r.inv() * base_r * r).magnitude() * 180 / np.pi)}


def fit(d):
    convention(d)
    source, target = points(d["source_weapon_points"]), points(d["target_hand_points"])
    if source.shape != target.shape or len(source) < 3:
        raise ValueError("Need at least three corresponding points")
    weights = array(d["weights"], (len(source),))
    if (weights < 0).any() or weights.sum() <= 0:
        raise ValueError("Weights must be nonnegative with a positive sum")
    weights /= weights.sum()
    cs = np.sum(source * weights[:, None], axis=0)
    ct = np.sum(target * weights[:, None], axis=0)
    a, b = (source - cs) * np.sqrt(weights[:, None]), (target - ct) * np.sqrt(weights[:, None])
    if min(np.linalg.matrix_rank(a), np.linalg.matrix_rank(b)) < 2:
        raise ValueError("Correspondences are collinear/degenerate; orientation is not determined")
    r, _ = R.align_vectors(a, b)
    p = cs - r.apply(ct)
    errors = np.linalg.norm(r.apply(target) + p - source, axis=1)
    return {"coordinate_space": d["coordinate_space"],
            "desired": {"position": p.tolist(), "rotation": r.as_quat().tolist()},
            "cached": d.get("cached"), "rms_mm": float(np.sqrt(np.sum(weights * errors**2)) * 1000),
            "max_mm": float(errors.max() * 1000), "scale_fitted": False,
            "status": "candidate_requires_runtime_validation"}


def hulls(d):
    result = []
    for c in d["colliders"]:
        h = array(c["planes"]) if "planes" in c else ConvexHull(points(c["vertices"])).equations
        if h.ndim != 2 or h.shape[1] != 4 or len(h) < 4:
            raise ValueError("Hull needs at least four [nx,ny,nz,d] planes")
        norms = np.linalg.norm(h[:, :3], axis=1)
        if (norms < 1e-10).any():
            raise ValueError("Invalid hull normal")
        result.append(h / norms[:, None])
    if not result:
        raise ValueError("No colliders; cannot claim clearance")
    return result


def triangles(d, count):
    raw = np.asarray(d.get("triangles", []))
    if raw.size == 0:
        return np.empty((0, 3), dtype=int)
    if raw.ndim != 2 or raw.shape[1] != 3 or not np.equal(raw, raw.astype(int)).all():
        raise ValueError("Expected Mx3 triangle indices")
    ids = raw.astype(int)
    if ids.min() < 0 or ids.max() >= count:
        raise ValueError("Triangle index out of range")
    return ids


def samples(v, t):
    return np.concatenate([v, v[t].mean(axis=1)]) if len(t) else v


def clearance(p, colliders):
    # Outward planes: max < 0 is inside one convex hull. min combines solids.
    return np.min([np.max(p @ h[:, :3].T + h[:, 3], axis=1) for h in colliders], axis=0)


def verify(d, threshold):
    convention(d)
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("clearance-mm must be nonnegative")
    v = points(d["vertices"])
    t = triangles(d, len(v))
    dist = clearance(samples(v, t), hulls(d))
    return {"passed": bool(np.all(dist >= threshold / 1000)), "vertices": len(v),
            "triangle_centers": len(t), "samples": len(dist), "inside": int((dist < 0).sum()),
            "below_required_clearance": int((dist < threshold / 1000).sum()),
            "minimum_plane_clearance_mm": float(dist.min() * 1000), "required_clearance_mm": threshold,
            "claim": "finite vertex/triangle-center samples against supplied conservative convex hulls; not continuous mesh collision proof"}


def refine(d, threshold, max_translation, max_rotation, muscle_limit):
    """Local LBS/muscle-Jacobian adjustment around an actual runtime snapshot."""
    convention(d)
    if min(threshold, max_translation, max_rotation, muscle_limit) <= 0:
        raise ValueError("Refinement clearance and bounds must be positive")
    skin = d["skin"]
    joints, bones = skin["joints"], skin["bones"]
    if not joints or joints[0]["parent"] != -1:
        raise ValueError("First joint must be wrist, with parent=-1")
    q0 = R.from_quat(array([j["q"] for j in joints], (len(joints), 4)))
    local_p = points([j["p"] for j in joints])
    parents = [j["parent"] for j in joints]
    if any(not isinstance(p, int) or p < 0 or p >= i for i, p in enumerate(parents[1:], 1)):
        raise ValueError("Joints must be ordered parent before child")
    base_b = array([b["matrix"] for b in bones]).reshape(-1, 4, 4)
    binds = array([b["bind"] for b in bones]).reshape(-1, 4, 4)
    joint_ids = np.asarray([b["joint"] for b in bones], dtype=int)
    if (joint_ids < -1).any() or (joint_ids >= len(joints)).any():
        raise ValueError("Invalid bone joint mapping")
    sv = skin["vertices"]
    verts = np.c_[points([v["p"] for v in sv]), np.ones(len(sv))]
    indices = np.asarray([v["indices"] for v in sv], dtype=int)
    weights = array([v["weights"] for v in sv], indices.shape)
    if indices.shape != (len(sv), 4) or indices.min() < 0 or indices.max() >= len(bones):
        raise ValueError("Expected four valid bone indices per vertex")
    if (weights < 0).any() or not np.allclose(weights.sum(axis=1), 1, atol=1e-4):
        raise ValueError("Skin weights must sum to one")
    bound = np.einsum("nkij,nj->nki", binds[indices], verts)
    basis = array(d["muscle_basis"])
    if basis.ndim != 3 or basis.shape[1:] != (len(joints) - 1, 3) or not len(basis):
        raise ValueError("muscle_basis must be M x finger-joints x 3; rad per muscle unit")
    wrist_p = array(d["wrist"]["position"], (3,))
    wrist_r = rotation(d["wrist"]["rotation"])
    measured = points(d["vertices"])
    if len(measured) != len(sv):
        raise ValueError("Skin and measured vertex ordering/count must match")
    tris, hs = triangles(d, len(measured)), hulls(d)

    def evaluate(x):
        angles = np.einsum("m,mjk->jk", x[6:], basis)
        local_r = q0.as_matrix()
        local_r[1:] = local_r[1:] @ R.from_rotvec(angles).as_matrix()
        matrices = np.repeat(np.eye(4)[None], len(joints), axis=0)
        for i in range(1, len(joints)):
            m = np.eye(4)
            m[:3, :3], m[:3, 3] = local_r[i], local_p[i]
            matrices[i] = matrices[parents[i]] @ m
        b = base_b.copy()
        select = joint_ids >= 0
        b[select] = matrices[joint_ids[select]]
        v = np.sum(np.einsum("nkij,nkj->nki", b[indices], bound) * weights[:, :, None], axis=1)[:, :3]
        r, p = R.from_rotvec(x[3:6]) * wrist_r, wrist_p + x[:3]
        return r.apply(v) + p, r, p, angles

    zero = np.zeros(6 + len(basis))
    reconstruction = float(np.sqrt(np.mean(np.sum((evaluate(zero)[0] - measured)**2, axis=1))) * 1000)
    if reconstruction > 0.1:
        raise ValueError(f"LBS reconstruction error {reconstruction:.4f} mm > 0.1 mm; fix data before optimizing")

    def residual(x):
        v = evaluate(x)[0]
        dist = clearance(samples(v, tris), hs)
        return np.r_[np.minimum(dist - threshold / 1000, 0) * 100 / np.sqrt(len(dist)),
                     ((v - measured) / np.sqrt(len(v))).ravel(), x[:3] * .1,
                     x[3:6] * .001, x[6:] * .0005]

    bounds = np.r_[[max_translation] * 3, [np.deg2rad(max_rotation)] * 3, [muscle_limit] * len(basis)]
    solved = least_squares(residual, zero, bounds=(-bounds, bounds), max_nfev=100)
    v, r, p, angles = evaluate(solved.x)
    checked = verify({**d, "vertices": v.tolist()}, threshold)
    return {"coordinate_space": d["coordinate_space"], "desired": {"position": p.tolist(), "rotation": r.as_quat().tolist()},
            "cached": d.get("cached"), "finger_rotations": [
                {"name": j["name"], "rotation": q.tolist()}
                for j, q in zip(joints[1:], (q0[1:] * R.from_rotvec(angles)).as_quat())],
            "muscle_deltas": solved.x[6:].tolist(), "offline_check": checked,
            "reconstruction_rms_mm": reconstruction, "solver_converged": bool(solved.success),
            "status": "candidate_requires_resampling_and_new_runtime_BakeMesh"}


def self_test():
    results = []
    frame = {"coordinate_space": "weapon-meters-xyzw"}
    # Noncommuting rotations detect the common inverse/multiplication-order bug.
    base, delta = R.from_euler("x", 70, degrees=True), R.from_euler("z", -35, degrees=True)
    test = {**frame, "cached": {"position": [.1, 0, 0], "rotation": base.as_quat().tolist()},
            "desired": {"position": [.12, -.03, .01], "rotation": (base * delta).as_quat().tolist()}}
    got = offset(test, .2)
    assert (rotation(got["rotation"]).inv() * delta).magnitude() < 1e-8
    assert np.allclose(got["position"], [.02, -.03, .01])
    results.append("noncommuting quaternion and position roundtrip")
    target = np.array([[0., 0, 0], [.1, 0, 0], [0, .1, 0], [0, 0, .1]])
    source = delta.apply(target) + [.2, -.1, .3]
    f = fit({**frame, "source_weapon_points": source.tolist(), "target_hand_points": target.tolist(), "weights": [1, 2, 3, 4]})
    assert f["rms_mm"] < 1e-6
    results.append("known rigid transform without scale")
    cube = [[x, y, z] for x in [-1, 1] for y in [-1, 1] for z in [-1, 1]]
    check = {**frame, "vertices": [[2, 0, 0], [0, 2, 0], [-2, -2, 0]], "triangles": [[0, 1, 2]], "colliders": [{"vertices": cube}]}
    assert verify(check, 0)["inside"] == 1
    results.append("triangle center catches collision missed by vertices")
    for bad in [{**test, "coordinate_space": "world"}, {**test, "desired": {"position": [3, 0, 0], "rotation": [0, 0, 0, 1]}}]:
        try:
            offset(bad, .2)
        except ValueError:
            continue
        raise AssertionError("Unsafe offset input was accepted")
    results.append("frame and offset-range rejection")
    case = json.loads((Path(__file__).resolve().parents[1] / "examples/synthetic-clearance.json").read_text(encoding="utf-8"))
    measured = verify(case, .5)
    assert measured["passed"] and measured["samples"] == case["expected_samples"]
    assert abs(measured["minimum_plane_clearance_mm"] - case["expected_clearance_mm"]) < .01
    assert not verify(case, 3)["passed"]
    results.append("synthetic clearance pass and stricter-threshold rejection")
    return {"passed": True, "checks": results, "synthetic_case": measured}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["fit", "offset", "verify", "refine", "self-test"]:
        p = sub.add_parser(name)
        if name != "self-test":
            p.add_argument("--input", required=True, type=Path)
        p.add_argument("--output", required=True, type=Path)
        if name == "offset":
            p.add_argument("--max-position-m", required=True, type=float)
        if name in ["verify", "refine"]:
            p.add_argument("--clearance-mm", required=True, type=float)
        if name == "refine":
            p.add_argument("--max-translation-m", required=True, type=float)
            p.add_argument("--max-rotation-deg", required=True, type=float)
            p.add_argument("--muscle-limit", required=True, type=float)
    args = parser.parse_args()
    try:
        if args.command != "self-test" and args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must differ")
        if args.output.suffix.lower() != ".json":
            raise ValueError("Output must be a JSON evidence file, not a Unity asset")
        if args.command == "self-test":
            result = self_test()
        else:
            raw = args.input.read_bytes()
            d = json.loads(raw.decode("utf-8-sig"))
            if args.command == "fit": result = fit(d)
            elif args.command == "offset": result = offset(d, args.max_position_m)
            elif args.command == "verify": result = verify(d, args.clearance_mm)
            else: result = refine(d, args.clearance_mm, args.max_translation_m, args.max_rotation_deg, args.muscle_limit)
            result["input_sha256"] = hashlib.sha256(raw).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(f"Written: {args.output}")
        return 1 if result.get("passed") is False else 0
    except (ValueError, KeyError, OSError, AssertionError) as exc:
        print(f"Calibration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
