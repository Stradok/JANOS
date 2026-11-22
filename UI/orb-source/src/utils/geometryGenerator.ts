import * as THREE from 'three';

export interface FragmentMeshInstance {
  mesh: THREE.Mesh;
  centroid: THREE.Vector3;
  direction: THREE.Vector3;
  basePosition: THREE.Vector3;
  baseQuaternion: THREE.Quaternion;
  rotationAxis: THREE.Vector3;
  rotationRate: number;
  maxDisplacement: number;
  phaseOffset: number;
}

/**
 * Generates streamlined, precision-engineered curved reactor housing panels
 * with substantial physical wall thickness, micro-chamfered edges, and smooth curvature.
 */
export function generateSphericalFragments(
  outerRadius: number = 2.05,
  innerRadius: number = 1.78,
  latSegments: number = 5,
  lonSegments: number = 10,
  shellMaterial: THREE.Material
): { group: THREE.Group; fragments: FragmentMeshInstance[] } {
  const group = new THREE.Group();
  const fragments: FragmentMeshInstance[] = [];

  for (let lat = 0; lat < latSegments; lat++) {
    const theta1 = (lat / latSegments) * Math.PI;
    const theta2 = ((lat + 1) / latSegments) * Math.PI;

    // Distribute panels evenly around the sphere
    const rowSlices = Math.max(3, Math.round(lonSegments * Math.sin((theta1 + theta2) / 2)));

    for (let lon = 0; lon < rowSlices; lon++) {
      const phi1 = (lon / rowSlices) * Math.PI * 2;
      const phi2 = ((lon + 1) / rowSlices) * Math.PI * 2;

      // Higher subdivision per panel for perfectly smooth curvature
      const subThetaSteps = 6;
      const subPhiSteps = 6;

      const positions: number[] = [];
      const normals: number[] = [];
      const uvs: number[] = [];
      const indices: number[] = [];

      const outerVerts: THREE.Vector3[][] = [];
      const innerVerts: THREE.Vector3[][] = [];

      // Slight gap between adjacent panels when assembled for clean panel seams
      const marginTheta = (theta2 - theta1) * 0.035;
      const marginPhi = (phi2 - phi1) * 0.035;

      const tStart = theta1 + marginTheta;
      const tEnd = theta2 - marginTheta;
      const pStart = phi1 + marginPhi;
      const pEnd = phi2 - marginPhi;

      for (let i = 0; i <= subThetaSteps; i++) {
        outerVerts[i] = [];
        innerVerts[i] = [];
        const t = tStart + (tEnd - tStart) * (i / subThetaSteps);

        for (let j = 0; j <= subPhiSteps; j++) {
          const p = pStart + (pEnd - pStart) * (j / subPhiSteps);

          const xo = outerRadius * Math.sin(t) * Math.cos(p);
          const yo = outerRadius * Math.cos(t);
          const zo = outerRadius * Math.sin(t) * Math.sin(p);
          outerVerts[i][j] = new THREE.Vector3(xo, yo, zo);

          const xi = innerRadius * Math.sin(t) * Math.cos(p);
          const yi = innerRadius * Math.cos(t);
          const zi = innerRadius * Math.sin(t) * Math.sin(p);
          innerVerts[i][j] = new THREE.Vector3(xi, yi, zi);
        }
      }

      // Calculate centroid of this panel
      const centroid = new THREE.Vector3();
      let totalV = 0;
      for (let i = 0; i <= subThetaSteps; i++) {
        for (let j = 0; j <= subPhiSteps; j++) {
          centroid.add(outerVerts[i][j]);
          totalV++;
        }
      }
      centroid.divideScalar(totalV);

      const geom = new THREE.BufferGeometry();

      // 1. Build outer curved face (smooth normals outwards)
      for (let i = 0; i < subThetaSteps; i++) {
        for (let j = 0; j < subPhiSteps; j++) {
          const v0 = outerVerts[i][j].clone().sub(centroid);
          const v1 = outerVerts[i + 1][j].clone().sub(centroid);
          const v2 = outerVerts[i + 1][j + 1].clone().sub(centroid);
          const v3 = outerVerts[i][j + 1].clone().sub(centroid);

          const idx = positions.length / 3;
          positions.push(
            v0.x, v0.y, v0.z,
            v1.x, v1.y, v1.z,
            v2.x, v2.y, v2.z,
            v3.x, v3.y, v3.z
          );

          const n0 = outerVerts[i][j].clone().normalize();
          const n1 = outerVerts[i + 1][j].clone().normalize();
          const n2 = outerVerts[i + 1][j + 1].clone().normalize();
          const n3 = outerVerts[i][j + 1].clone().normalize();

          normals.push(
            n0.x, n0.y, n0.z,
            n1.x, n1.y, n1.z,
            n2.x, n2.y, n2.z,
            n3.x, n3.y, n3.z
          );

          uvs.push(
            j / subPhiSteps, i / subThetaSteps,
            j / subPhiSteps, (i + 1) / subThetaSteps,
            (j + 1) / subPhiSteps, (i + 1) / subThetaSteps,
            (j + 1) / subPhiSteps, i / subThetaSteps
          );

          indices.push(idx, idx + 1, idx + 2, idx, idx + 2, idx + 3);
        }
      }

      // 2. Build inner face (facing towards central core)
      for (let i = 0; i < subThetaSteps; i++) {
        for (let j = 0; j < subPhiSteps; j++) {
          const v0 = innerVerts[i][j].clone().sub(centroid);
          const v1 = innerVerts[i + 1][j].clone().sub(centroid);
          const v2 = innerVerts[i + 1][j + 1].clone().sub(centroid);
          const v3 = innerVerts[i][j + 1].clone().sub(centroid);

          const idx = positions.length / 3;
          positions.push(
            v0.x, v0.y, v0.z,
            v1.x, v1.y, v1.z,
            v2.x, v2.y, v2.z,
            v3.x, v3.y, v3.z
          );

          const n0 = innerVerts[i][j].clone().normalize().negate();
          const n1 = innerVerts[i + 1][j].clone().normalize().negate();
          const n2 = innerVerts[i + 1][j + 1].clone().normalize().negate();
          const n3 = innerVerts[i][j + 1].clone().normalize().negate();

          normals.push(
            n0.x, n0.y, n0.z,
            n1.x, n1.y, n1.z,
            n2.x, n2.y, n2.z,
            n3.x, n3.y, n3.z
          );

          uvs.push(
            j / subPhiSteps, i / subThetaSteps,
            j / subPhiSteps, (i + 1) / subThetaSteps,
            (j + 1) / subPhiSteps, (i + 1) / subThetaSteps,
            (j + 1) / subPhiSteps, i / subThetaSteps
          );

          indices.push(idx, idx + 2, idx + 1, idx, idx + 3, idx + 2);
        }
      }

      // 3. Build beveled thickness side walls
      for (let j = 0; j < subPhiSteps; j++) {
        addQuadWall(outerVerts[0][j], outerVerts[0][j + 1], innerVerts[0][j + 1], innerVerts[0][j], centroid, positions, normals, uvs, indices);
        addQuadWall(outerVerts[subThetaSteps][j + 1], outerVerts[subThetaSteps][j], innerVerts[subThetaSteps][j], innerVerts[subThetaSteps][j + 1], centroid, positions, normals, uvs, indices);
      }
      for (let i = 0; i < subThetaSteps; i++) {
        addQuadWall(outerVerts[i + 1][0], outerVerts[i][0], innerVerts[i][0], innerVerts[i + 1][0], centroid, positions, normals, uvs, indices);
        addQuadWall(outerVerts[i][subPhiSteps], outerVerts[i + 1][subPhiSteps], innerVerts[i + 1][subPhiSteps], innerVerts[i][subPhiSteps], centroid, positions, normals, uvs, indices);
      }

      geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geom.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
      geom.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
      geom.setIndex(indices);

      const mesh = new THREE.Mesh(geom, shellMaterial);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.position.copy(centroid);

      const direction = centroid.clone().normalize();
      const rotAxis = new THREE.Vector3(
        (Math.random() - 0.5) * 2,
        (Math.random() - 0.5) * 2,
        (Math.random() - 0.5) * 2
      ).normalize();

      const maxDist = 1.3 + Math.random() * 1.4;
      const rotRate = (0.18 + Math.random() * 0.35) * (Math.random() > 0.5 ? 1 : -1);
      const phase = Math.random() * 0.2;

      group.add(mesh);
      fragments.push({
        mesh,
        centroid: centroid.clone(),
        direction,
        basePosition: centroid.clone(),
        baseQuaternion: mesh.quaternion.clone(),
        rotationAxis: rotAxis,
        rotationRate: rotRate,
        maxDisplacement: maxDist,
        phaseOffset: phase,
      });
    }
  }

  return { group, fragments };
}

function addQuadWall(
  p1: THREE.Vector3,
  p2: THREE.Vector3,
  p3: THREE.Vector3,
  p4: THREE.Vector3,
  centroid: THREE.Vector3,
  positions: number[],
  normals: number[],
  uvs: number[],
  indices: number[]
) {
  const v1 = p1.clone().sub(centroid);
  const v2 = p2.clone().sub(centroid);
  const v3 = p3.clone().sub(centroid);
  const v4 = p4.clone().sub(centroid);

  const edgeA = v2.clone().sub(v1);
  const edgeB = v4.clone().sub(v1);
  const normal = new THREE.Vector3().crossVectors(edgeA, edgeB).normalize();

  const idx = positions.length / 3;
  positions.push(
    v1.x, v1.y, v1.z,
    v2.x, v2.y, v2.z,
    v3.x, v3.y, v3.z,
    v4.x, v4.y, v4.z
  );

  normals.push(
    normal.x, normal.y, normal.z,
    normal.x, normal.y, normal.z,
    normal.x, normal.y, normal.z,
    normal.x, normal.y, normal.z
  );

  uvs.push(0, 0, 1, 0, 1, 1, 0, 1);
  indices.push(idx, idx + 1, idx + 2, idx, idx + 2, idx + 3);
}
