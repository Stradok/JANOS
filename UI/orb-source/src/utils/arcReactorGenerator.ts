import * as THREE from 'three';
import { ThemeColors } from '../types';

export interface ArcReactorInstance {
  group: THREE.Group;
  update: (time: number, expansion: number) => void;
  dispose: () => void;
}

/**
 * Procedurally constructs a refined, high-density 3D Core Reactor.
 * Features:
 * - Radial falloff core shader: bright white-hot center cooling into saturated ruby crimson
 * - Solid multi-element chrome condenser rings and dark titanium armor chassis
 * - Dense electromagnetic induction coils with copper windings and titanium clamps
 * - High specular response to studio environment lighting
 */
export function createArcReactor(theme: ThemeColors): ArcReactorInstance {
  const group = new THREE.Group();

  // Premium Machined Materials
  const heavyTitaniumMat = new THREE.MeshStandardMaterial({
    color: 0x161a22,
    metalness: 0.94,
    roughness: 0.22,
    envMapIntensity: 2.6,
  });

  const tungstenArmorMat = new THREE.MeshStandardMaterial({
    color: 0x0e1116,
    metalness: 0.92,
    roughness: 0.35,
    envMapIntensity: 2.0,
  });

  const chromeTrimMat = new THREE.MeshStandardMaterial({
    color: 0xccd4e0,
    metalness: 0.98,
    roughness: 0.12,
    envMapIntensity: 3.2,
  });

  const solidCopperMat = new THREE.MeshStandardMaterial({
    color: 0xd4622b,
    metalness: 0.92,
    roughness: 0.25,
    envMapIntensity: 2.2,
  });

  const darkCeramicMat = new THREE.MeshStandardMaterial({
    color: 0x1c1416,
    metalness: 0.4,
    roughness: 0.5,
  });

  const corePlasmaColor = new THREE.Color(theme.glowColor);
  const coreOuterColor = new THREE.Color(theme.coreOuter);

  // 1. Radial Falloff Core Shader (White-hot at center, cooling into deep saturated crimson edge)
  const coreShaderGeo = new THREE.SphereGeometry(0.72, 48, 48);
  const coreShaderMat = new THREE.ShaderMaterial({
    uniforms: {
      innerColor: { value: new THREE.Color(0xffffff) },
      midColor: { value: new THREE.Color('#ff1838') },
      edgeColor: { value: coreOuterColor },
      time: { value: 0.0 },
      expansion: { value: 0.0 },
    },
    vertexShader: `
      varying vec3 vNormal;
      varying vec3 vPosition;
      varying vec3 vViewDir;
      void main() {
        vNormal = normalize(normalMatrix * normal);
        vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
        vPosition = position;
        vViewDir = normalize(-mvPos.xyz);
        gl_Position = projectionMatrix * mvPos;
      }
    `,
    fragmentShader: `
      uniform vec3 innerColor;
      uniform vec3 midColor;
      uniform vec3 edgeColor;
      uniform float time;
      uniform float expansion;
      varying vec3 vNormal;
      varying vec3 vPosition;
      varying vec3 vViewDir;

      void main() {
        // Dot product between view direction and surface normal (1 at center, 0 at silhouette edge)
        float viewDot = max(0.0, dot(vNormal, vViewDir));
        
        // Micro plasma pulse shimmer
        float shimmer = 0.03 * sin(vPosition.y * 12.0 + time * 4.0) * cos(vPosition.x * 12.0 + time * 3.0);
        float falloff = clamp(pow(viewDot, 1.8) + shimmer, 0.0, 1.0);

        // Gradient from rim edge (dark ruby) -> mid (intense red) -> center (white hot)
        vec3 col = mix(edgeColor * 0.85, midColor * 1.8, smoothstep(0.0, 0.55, falloff));
        col = mix(col, innerColor * 2.2, smoothstep(0.55, 1.0, falloff));

        gl_FragColor = vec4(col, 1.0);
      }
    `,
    toneMapped: true,
  });
  const centralCoreMesh = new THREE.Mesh(coreShaderGeo, coreShaderMat);
  group.add(centralCoreMesh);

  // 2. Translucent High-Density Plasma Shell
  const densePlasmaGeo = new THREE.SphereGeometry(0.86, 36, 36);
  const densePlasmaMat = new THREE.MeshStandardMaterial({
    color: coreOuterColor,
    emissive: corePlasmaColor,
    emissiveIntensity: 1.4,
    transparent: true,
    opacity: 0.65,
    roughness: 0.1,
    metalness: 0.3,
  });
  const densePlasma = new THREE.Mesh(densePlasmaGeo, densePlasmaMat);
  group.add(densePlasma);

  // 3. Concentric Stepped Chrome Condenser Rings
  const lensStackGroup = new THREE.Group();
  for (let l = 0; l < 4; l++) {
    const lensRadius = 0.56 + l * 0.11;
    const lensTube = 0.042 + l * 0.008;
    const stepTorusGeo = new THREE.TorusGeometry(lensRadius, lensTube, 16, 48);
    const stepTorus = new THREE.Mesh(stepTorusGeo, chromeTrimMat);
    stepTorus.rotation.x = Math.PI / 2;
    lensStackGroup.add(stepTorus);

    const stepTorusV = new THREE.Mesh(stepTorusGeo, heavyTitaniumMat);
    lensStackGroup.add(stepTorusV);
  }
  group.add(lensStackGroup);

  // 4. Concentric High-Density Stator Rings & Induction Coils
  const ringAssemblies: {
    ringGroup: THREE.Group;
    stator: THREE.Mesh;
    coilsGroup: THREE.Group;
    glowRingMat: THREE.MeshBasicMaterial;
    rotSpeed: number;
  }[] = [];

  const orientations = [
    new THREE.Euler(0, 0, 0),
    new THREE.Euler(Math.PI / 2, 0, 0),
    new THREE.Euler(0, Math.PI / 2, 0),
  ];

  orientations.forEach((euler, planeIdx) => {
    const ringGroup = new THREE.Group();
    ringGroup.rotation.copy(euler);

    const radius = 1.30;

    // Solid Heavy Machined Titanium Main Ring
    const mainTorusGeo = new THREE.TorusGeometry(radius, 0.085, 20, 72);
    const mainTorus = new THREE.Mesh(mainTorusGeo, heavyTitaniumMat);
    ringGroup.add(mainTorus);

    // Stepped Inner Armor Ring
    const innerArmorGeo = new THREE.TorusGeometry(radius - 0.13, 0.05, 16, 64);
    const innerArmor = new THREE.Mesh(innerArmorGeo, tungstenArmorMat);
    ringGroup.add(innerArmor);

    // Glowing Conduit Channel
    const glowRingGeo = new THREE.TorusGeometry(radius - 0.065, 0.028, 12, 64);
    const glowRingMat = new THREE.MeshBasicMaterial({
      color: corePlasmaColor,
    });
    const glowRing = new THREE.Mesh(glowRingGeo, glowRingMat);
    ringGroup.add(glowRing);

    // Inner Chrome Stator
    const statorGeo = new THREE.TorusGeometry(radius - 0.22, 0.036, 16, 56);
    const stator = new THREE.Mesh(statorGeo, chromeTrimMat);
    ringGroup.add(stator);

    // 12 Dense Solid Copper Electromagnetic Induction Coils
    const coilsGroup = new THREE.Group();
    const coilCount = 12;
    const coilBlockGeo = new THREE.BoxGeometry(0.16, 0.2, 0.15);
    const clampGeo = new THREE.BoxGeometry(0.08, 0.24, 0.18);
    const corePinGeo = new THREE.CylinderGeometry(0.02, 0.02, 0.22, 8);

    for (let c = 0; c < coilCount; c++) {
      const angle = (c / coilCount) * Math.PI * 2;
      const x = Math.cos(angle) * radius;
      const y = Math.sin(angle) * radius;

      const singleCoil = new THREE.Group();
      singleCoil.position.set(x, y, 0);
      singleCoil.rotation.z = angle + Math.PI / 2;

      // Solid Copper Induction Winding Block
      const coilMesh = new THREE.Mesh(coilBlockGeo, solidCopperMat);
      singleCoil.add(coilMesh);

      // Dark Titanium Compression Clamp
      const clampMesh = new THREE.Mesh(clampGeo, tungstenArmorMat);
      singleCoil.add(clampMesh);

      // Ceramic insulator base
      const ceramicBaseGeo = new THREE.BoxGeometry(0.13, 0.035, 0.13);
      const ceramicMesh = new THREE.Mesh(ceramicBaseGeo, darkCeramicMat);
      ceramicMesh.position.y = -0.1;
      singleCoil.add(ceramicMesh);

      // Chrome Terminal Grounding Pin
      const pinMesh = new THREE.Mesh(corePinGeo, chromeTrimMat);
      pinMesh.rotation.x = Math.PI / 2;
      singleCoil.add(pinMesh);

      coilsGroup.add(singleCoil);
    }
    ringGroup.add(coilsGroup);

    group.add(ringGroup);

    ringAssemblies.push({
      ringGroup,
      stator,
      coilsGroup,
      glowRingMat,
      rotSpeed: (planeIdx === 1 ? -0.16 : 0.2) * (planeIdx === 2 ? 0.8 : 1.0),
    });
  });

  return {
    group,
    update: (time: number, expansion: number) => {
      coreShaderMat.uniforms.time.value = time;
      coreShaderMat.uniforms.expansion.value = expansion;

      // Dense breathing pulse
      const pulse = 1.0 + Math.sin(time * 3.6) * 0.02 + expansion * 0.05;
      centralCoreMesh.scale.setScalar(pulse);
      densePlasma.scale.setScalar(1.0 + Math.sin(time * 4.0) * 0.03 + expansion * 0.07);

      // Rotate stator rings
      ringAssemblies.forEach((assembly) => {
        assembly.ringGroup.rotation.z += assembly.rotSpeed * 0.01;
        assembly.stator.rotation.z -= assembly.rotSpeed * 0.014;
      });

      lensStackGroup.rotation.y = time * 0.08;
      lensStackGroup.rotation.z = Math.sin(time * 0.12) * 0.08;
    },
    dispose: () => {
      heavyTitaniumMat.dispose();
      tungstenArmorMat.dispose();
      chromeTrimMat.dispose();
      solidCopperMat.dispose();
      darkCeramicMat.dispose();
      coreShaderGeo.dispose();
      coreShaderMat.dispose();
      densePlasmaGeo.dispose();
      densePlasmaMat.dispose();
      ringAssemblies.forEach((a) => {
        a.glowRingMat.dispose();
      });
    },
  };
}
