"""Hand-built meshes, for geometry raylib's generators don't cover.

The holes need to be real: a punched surface with a lined well you can see
down into. A cylinder sitting under a solid plane just reads as a painted
black disc, which is exactly what it looked like.
"""

import math

import pyray as rl

# raylib keeps the CPU-side pointers after upload_mesh, so the ffi buffers have
# to outlive the call.
_KEEP = []


def make_mesh(pos, nrm, uv, idx):
    m = rl.Mesh()
    m.vertexCount = len(pos) // 3
    m.triangleCount = len(idx) // 3
    vb = rl.ffi.new("float[]", pos)
    nb = rl.ffi.new("float[]", nrm)
    tb = rl.ffi.new("float[]", uv)
    ib = rl.ffi.new("unsigned short[]", idx)
    m.vertices, m.normals, m.texcoords, m.indices = vb, nb, tb, ib
    rl.upload_mesh(m, False)
    _KEEP.append((m, vb, nb, tb, ib))
    return m


def tube(radius, depth, segments=40, uv_repeat=3.0):
    """Open cylinder with inward-facing normals - the wall of a drilled hole.

    Normals point at the axis so the interior lights correctly; a stock
    cylinder lights its outside and the well looks inside-out.
    """
    pos, nrm, uv, idx = [], [], [], []
    for i in range(segments + 1):
        a = i / segments * math.tau
        cx, sz = math.cos(a), math.sin(a)
        u = i / segments * uv_repeat
        for j, y in enumerate((0.0, -depth)):
            pos += [cx * radius, y, sz * radius]
            nrm += [-cx, 0.0, -sz]
            uv += [u, float(j)]
    for i in range(segments):
        a = i * 2
        b = (i + 1) * 2
        idx += [a, b, a + 1, b, b + 1, a + 1]
    return make_mesh(pos, nrm, uv, idx)


def ring(inner, outer, segments=40, y=0.0, bevel=0.0):
    """Flat annulus, used for the chamfered lip around each hole."""
    pos, nrm, uv, idx = [], [], [], []
    for i in range(segments + 1):
        a = i / segments * math.tau
        cx, sz = math.cos(a), math.sin(a)
        u = i / segments
        pos += [cx * outer, y, sz * outer]
        nrm += [0.0, 1.0, 0.0]
        uv += [u, 1.0]
        pos += [cx * inner, y - bevel, sz * inner]
        n = rl.vector3_normalize(rl.Vector3(cx * bevel, outer - inner, sz * bevel))
        nrm += [n.x, n.y, n.z]
        uv += [u, 0.0]
    for i in range(segments):
        a = i * 2
        b = (i + 1) * 2
        idx += [a, b, a + 1, b, b + 1, a + 1]
    return make_mesh(pos, nrm, uv, idx)


def disc(radius, segments=40, y=0.0):
    pos = [0.0, y, 0.0]
    nrm = [0.0, 1.0, 0.0]
    uv = [0.5, 0.5]
    idx = []
    for i in range(segments + 1):
        a = i / segments * math.tau
        cx, sz = math.cos(a), math.sin(a)
        pos += [cx * radius, y, sz * radius]
        nrm += [0.0, 1.0, 0.0]
        uv += [cx * 0.5 + 0.5, sz * 0.5 + 0.5]
    for i in range(1, segments + 1):
        idx += [0, i, i + 1]
    return make_mesh(pos, nrm, uv, idx)


def cylinder(radius=0.5, height=1.0, segments=18, caps=True):
    """Cylinder centred on the origin, axis along Y.

    raylib's own cylinder is anchored at its base, so scaling one to make a
    wheel or a tree canopy silently offsets it by half its height. Centring it
    here means a transform does what it looks like it should.
    """
    pos, nrm, uv, idx = [], [], [], []
    hy = height / 2.0
    for i in range(segments + 1):
        a = i / segments * math.tau
        cx, sz = math.cos(a), math.sin(a)
        u = i / segments
        pos += [cx * radius, hy, sz * radius]
        nrm += [cx, 0.0, sz]
        uv += [u, 0.0]
        pos += [cx * radius, -hy, sz * radius]
        nrm += [cx, 0.0, sz]
        uv += [u, 1.0]
    for i in range(segments):
        a, b = i * 2, (i + 1) * 2
        idx += [a, a + 1, b, b, a + 1, b + 1]

    if caps:
        for sign, ny in ((hy, 1.0), (-hy, -1.0)):
            base = len(pos) // 3
            pos += [0.0, sign, 0.0]
            nrm += [0.0, ny, 0.0]
            uv += [0.5, 0.5]
            for i in range(segments + 1):
                a = i / segments * math.tau
                cx, sz = math.cos(a), math.sin(a)
                pos += [cx * radius, sign, sz * radius]
                nrm += [0.0, ny, 0.0]
                uv += [cx * 0.5 + 0.5, sz * 0.5 + 0.5]
            for i in range(1, segments + 1):
                if ny > 0:
                    idx += [base, base + i, base + i + 1]
                else:
                    idx += [base, base + i + 1, base + i]
    return make_mesh(pos, nrm, uv, idx)


def heightfield(heights, world_w, world_d, res=250):
    """Terrain mesh from a float heightfield, centred on the origin.

    Built by hand rather than with GenMeshHeightmap because that reads an
    8-bit image: over a 46 m range that quantises to 18 cm steps, and shallow
    slopes come out visibly terraced.

    `heights` is a 2-D numpy array in world units, indexed [z][x].
    """
    import numpy as np

    nz, nx = heights.shape
    res = min(res, 255)                      # 16-bit indices cap the grid
    u = np.linspace(0.0, 1.0, res)
    gz, gx = np.meshgrid(u, u, indexing="ij")

    # Bilinear sample of the source field.
    fx = gx * (nx - 1)
    fz = gz * (nz - 1)
    x0 = np.clip(fx.astype(np.int32), 0, nx - 2)
    z0 = np.clip(fz.astype(np.int32), 0, nz - 2)
    tx, tz = fx - x0, fz - z0
    h = (heights[z0, x0] * (1 - tx) * (1 - tz)
         + heights[z0, x0 + 1] * tx * (1 - tz)
         + heights[z0 + 1, x0] * (1 - tx) * tz
         + heights[z0 + 1, x0 + 1] * tx * tz)

    px = (gx - 0.5) * world_w
    pz = (gz - 0.5) * world_d
    verts = np.stack([px, h, pz], axis=-1).reshape(-1).astype(np.float32)

    dz, dx = np.gradient(h)
    cell_x = world_w / (res - 1)
    cell_z = world_d / (res - 1)
    nxv, nyv, nzv = -dx / cell_x, np.ones_like(h), -dz / cell_z
    inv = 1.0 / np.sqrt(nxv ** 2 + nyv ** 2 + nzv ** 2)
    norms = np.stack([nxv * inv, nyv * inv, nzv * inv],
                     axis=-1).reshape(-1).astype(np.float32)
    uvs = np.stack([gx, gz], axis=-1).reshape(-1).astype(np.float32)

    a = np.arange(res - 1)
    j, i = np.meshgrid(a, a, indexing="ij")
    v0 = (j * res + i).reshape(-1)
    tris = np.stack([v0, v0 + res, v0 + 1,
                     v0 + 1, v0 + res, v0 + res + 1],
                    axis=-1).reshape(-1).astype(np.uint16)

    m = rl.Mesh()
    m.vertexCount = res * res
    m.triangleCount = tris.size // 3
    vb = rl.ffi.new("float[]", verts.size)
    nb = rl.ffi.new("float[]", norms.size)
    tb = rl.ffi.new("float[]", uvs.size)
    ib = rl.ffi.new("unsigned short[]", tris.size)
    rl.ffi.memmove(vb, verts.tobytes(), verts.nbytes)
    rl.ffi.memmove(nb, norms.tobytes(), norms.nbytes)
    rl.ffi.memmove(tb, uvs.tobytes(), uvs.nbytes)
    rl.ffi.memmove(ib, tris.tobytes(), tris.nbytes)
    m.vertices, m.normals, m.texcoords, m.indices = vb, nb, tb, ib
    rl.upload_mesh(m, False)
    _KEEP.append((m, vb, nb, tb, ib))
    return m


def plane(size, subdivisions=1):
    """Flat quad in XZ centred on the origin, with 0..1 UVs."""
    pos, nrm, uv, idx = [], [], [], []
    n = subdivisions
    for j in range(n + 1):
        for i in range(n + 1):
            fx, fz = i / n, j / n
            pos += [(fx - 0.5) * size, 0.0, (fz - 0.5) * size]
            nrm += [0.0, 1.0, 0.0]
            uv += [fx, fz]
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + (n + 1)
            d = c + 1
            idx += [a, c, b, b, c, d]
    return make_mesh(pos, nrm, uv, idx)
