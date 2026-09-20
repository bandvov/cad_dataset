// export function findBuild123dPrompt(id) {
//   for (const category of BUILD123D_PROMPTS) {
//     const prompt = category.prompts.find(
//       (item) => item.id === id
//     );

//     if (prompt) {
//       return prompt;
//     }
//   }

//   return null;
// }
export function findBuild123dPrompt(id) {
  return BUILD123D_PROMPTS.find((item) => item.id === id) ?? null;
}

export const BUILD123D_PROMPTS = [
  {
    id: "loft-tapered-housing",
    name: "Loft — Tapered Housing",
    prompt:
      "Create a tapered rectangular housing using a loft between a 60x40 mm rectangle at z=0 and a 40x25 mm rectangle at z=50. Add a 5 mm wall thickness using a shell operation, leaving the top open.",
  },
  {
    id: "loft-transition",
    name: "Loft — Rectangular to Circular",
    prompt:
      "Create a smooth transition duct by lofting from a 60x40 mm rectangular profile at z=0 to a centered circular profile with diameter 35 mm at z=60. Keep both profiles aligned to the same axis.",
  },
  {
    id: "sweep-pipe",
    name: "Sweep — Curved Pipe",
    prompt:
      "Create a 20 mm diameter pipe by sweeping a circular profile along an S-shaped 3D path. The path should contain two tangent arcs with a straight section between them.",
  },
  {
    id: "sweep-rail",
    name: "Sweep — Rectangular Rail",
    prompt:
      "Create a rectangular rail by sweeping a 12x8 mm rectangular profile along a curved path consisting of a horizontal line, a 90-degree arc, and a vertical line. Keep the profile perpendicular to the path.",
  },
  {
    id: "revolve-knob",
    name: "Revolve — Knob",
    prompt:
      "Create a rotational knob by sketching a radial cross-section and revolving it 360 degrees around the Z axis. Include a cylindrical base, tapered shoulder, and rounded top profile.",
  },
  {
    id: "revolve-pulley",
    name: "Revolve — Pulley",
    prompt:
      "Create a pulley using a revolved cross-section. The profile should produce a central hub, two side flanges, and a V-shaped groove around the outer circumference.",
  },
  {
    id: "circular-bolt-pattern",
    name: "Circular Pattern — Bolt Holes",
    prompt:
      "Create a circular flange with a central bore and one bolt hole. Pattern the bolt hole around the Z axis 8 times over 360 degrees. Keep the holes equally spaced on a 60 mm bolt circle.",
  },
  {
    id: "partial-circular-pattern",
    name: "Circular Pattern — Partial Arc",
    prompt:
      "Create a circular base with one mounting boss and pattern the boss 5 times over a 180-degree arc rather than a full circle. Keep all instances equally spaced.",
  },
  {
    id: "linear-pattern",
    name: "Linear Pattern — Mounting Slots",
    prompt:
      "Create a rectangular mounting plate with one elongated slot near one edge. Create a linear pattern of 5 identical slots along the X axis with 20 mm spacing.",
  },
  {
    id: "mirror-features",
    name: "Mirror — Symmetric Bosses",
    prompt:
      "Create a rectangular plate with a cylindrical boss and a mounting hole on the left side. Mirror the boss and hole across the YZ plane so the final part is symmetric.",
  },
  {
    id: "mirror-pocket",
    name: "Mirror — Symmetric Pockets",
    prompt:
      "Create a rectangular block with a rectangular pocket cut into its left side. Mirror the pocket feature across the central YZ plane to create an identical pocket on the opposite side.",
  },
  {
    id: "multi-step-flange",
    name: "Multi-step — Pipe Flange",
    prompt:
      "Create a pipe flange as a multi-step feature: start with a cylindrical flange disk, add a raised central pipe boss, cut the central bore, create one bolt hole, then circular-pattern the bolt hole 6 times around the flange. Finish the outer edges with a small chamfer.",
  },
  {
    id: "multi-step-mounting-bracket",
    name: "Multi-step — Mounting Bracket",
    prompt:
      "Create an L-shaped mounting bracket. Start with two perpendicular plates, add a cylindrical mounting boss to one plate, cut its center hole, create a matching boss on the opposite side, and add two linear-patterned mounting holes to the base.",
  },
  {
    id: "shell-housing",
    name: "Shell — Electronics Housing",
    prompt:
      "Create a rectangular electronics enclosure with rounded outer edges. Hollow it using a shell operation with 3 mm wall thickness, leaving the top face open. Add four cylindrical mounting bosses inside the enclosure.",
  },
  {
    id: "fillet-chamfer-combination",
    name: "Fillet + Chamfer",
    prompt:
      "Create a rectangular mechanical block with a central through-hole. Apply 5 mm fillets to the four vertical outer edges and 2 mm chamfers around both sides of the central hole.",
  },
  {
    id: "lofted-nozzle",
    name: "Loft — Nozzle",
    prompt:
      "Create a nozzle using three loft profiles: a 50 mm diameter circle at z=0, a 35 mm diameter circle at z=30, and a 20 mm diameter circle at z=60. Add a 10 mm long cylindrical outlet at the top.",
  },
  {
    id: "sweep-cable-channel",
    name: "Sweep — Cable Channel",
    prompt:
      "Create a U-shaped cable channel by sweeping a rectangular 20x10 mm profile along a path made from a straight segment, a 180-degree arc, and another straight segment. Add a mounting flange at both ends.",
  },
  {
    id: "revolve-bearing",
    name: "Revolve — Bearing Ring",
    prompt:
      "Create a bearing ring by revolving a radial cross-section around the Z axis. The cross-section should include an inner bore, outer cylindrical surface, and rounded raceway groove.",
  },
  {
    id: "patterned-ribs",
    name: "Linear Pattern — Reinforcement Ribs",
    prompt:
      "Create a rectangular base plate with one triangular reinforcement rib along its length. Create a linear pattern of 4 identical ribs across the width with equal spacing.",
  },
  {
    id: "complex-patterned-cover",
    name: "Complex — Patterned Cover",
    prompt:
      "Create a circular cover with a central cylindrical boss. Add one radial ventilation slot, circular-pattern the slot 12 times around the center, and add four mounting holes using a separate circular pattern. Add a 2 mm chamfer to the outer edge.",
  },
];

export const COMPLEX_EXTRUSION_PROMPTS = [
  {
    id: "extrude-stepped-profile",
    name: "Extrude — Stepped Profile",
    prompt:
      "Create a 3D mechanical block by sketching an asymmetric stepped 2D profile on the XY plane and extruding it 30 mm. The profile should have multiple horizontal and vertical segments forming two different height levels.",
  },
  {
    id: "extrude-l-shaped-profile",
    name: "Extrude — L-shaped Profile",
    prompt:
      "Create an L-shaped solid by sketching an L-shaped 2D polygon on the XY plane and extruding it 40 mm. The two legs should have different widths.",
  },
  {
    id: "extrude-u-profile",
    name: "Extrude — U-shaped Profile",
    prompt:
      "Create a U-shaped channel by sketching a closed U-shaped profile on the XY plane and extruding it 50 mm. The channel should have 8 mm wall thickness and an open central region.",
  },
  {
    id: "extrude-t-profile",
    name: "Extrude — T Profile",
    prompt:
      "Create a T-shaped structural component by sketching a T-shaped closed profile on the XY plane and extruding it 60 mm. The vertical stem and horizontal flange should have different widths.",
  },
  {
    id: "extrude-dovetail",
    name: "Extrude — Dovetail Profile",
    prompt:
      "Create a dovetail rail by sketching a trapezoidal dovetail profile with a narrower top and wider base, then extrude it 80 mm. Add two small mounting holes through the base.",
  },
  {
    id: "extrude-keyway-profile",
    name: "Extrude — Keyway Profile",
    prompt:
      "Create a mechanical mounting block from a custom sketch containing a rectangular base, two semicircular ends, and a central keyway. Extrude the complete profile 25 mm.",
  },
  {
    id: "extrude-rounded-bracket",
    name: "Extrude — Rounded Bracket",
    prompt:
      "Create a mounting bracket by sketching a profile with straight segments and tangent arcs. The profile should have rounded outer corners, a narrow upper section, and a wider lower section. Extrude it 35 mm.",
  },
  {
    id: "extrude-profile-with-holes",
    name: "Extrude — Multi-hole Profile",
    prompt:
      "Create a rectangular mechanical plate from a sketch containing an irregular outer boundary and four internal circular holes. Extrude the sketch 12 mm so the holes become through-holes in the resulting solid.",
  },
  {
    id: "extrude-concentric-profile",
    name: "Extrude — Concentric Rings",
    prompt:
      "Create a circular mounting component using a sketch containing multiple concentric circular regions. Extrude the profile 15 mm to create a ring-shaped solid with a stepped internal bore.",
  },
  {
    id: "extrude-polygon-boss",
    name: "Extrude — Polygonal Boss",
    prompt:
      "Create a hexagonal mounting plate with an integrated raised octagonal boss. Build the base and boss from a sketch containing multiple connected regions, then extrude the main profile to create the solid.",
  },
  {
    id: "extrude-symmetric-profile",
    name: "Extrude — Symmetric Mechanical Profile",
    prompt:
      "Create a symmetric mechanical component from a sketch containing a central rectangular section, two angled side sections, and rounded outer ends. Use symmetry about the Y axis and extrude the resulting profile 30 mm.",
  },
  {
    id: "extrude-asymmetric-profile",
    name: "Extrude — Asymmetric Profile",
    prompt:
      "Create an asymmetric mounting component from a custom closed sketch. The profile should contain several straight segments, one angled edge, and two different-radius arcs. Extrude the profile 45 mm.",
  },
  {
    id: "extrude-ribbed-profile",
    name: "Extrude — Ribbed Profile",
    prompt:
      "Create a structural part from a sketch containing a central body and three triangular reinforcement sections integrated into the outer profile. Extrude the complete irregular profile 50 mm.",
  },
  {
    id: "extrude-fork-profile",
    name: "Extrude — Fork Profile",
    prompt:
      "Create a fork-shaped mechanical part by sketching two parallel arms connected by a rounded base. Include a circular hole at the end of each arm and extrude the sketch 20 mm.",
  },
  {
    id: "extrude-cam-profile",
    name: "Extrude — Cam Profile",
    prompt:
      "Create a cam plate by sketching an irregular closed profile made from several tangent arcs and short straight segments. Add a central circular bore and two smaller mounting holes, then extrude the profile 18 mm.",
  },
  {
    id: "extrude-flange-profile",
    name: "Extrude — Custom Flange",
    prompt:
      "Create a custom flange from a sketch with a circular outer boundary modified by four equally spaced rectangular mounting ears. Add a central circular bore and four bolt holes, then extrude the entire profile 12 mm.",
  },
  {
    id: "extrude-bracket-profile",
    name: "Extrude — Multi-region Bracket",
    prompt:
      "Create a complex bracket from a sketch containing an outer stepped profile, two internal circular holes, and a central elongated slot. Extrude the sketch 25 mm while preserving all internal voids.",
  },
  {
    id: "extrude-gear-like-profile",
    name: "Extrude — Gear-like Profile",
    prompt:
      "Create a gear-like plate by sketching a central circular region with twelve repeated tooth-shaped outer sections. Use a circular pattern in the sketch and then extrude the resulting 2D profile 10 mm.",
  },
  {
    id: "extrude-arched-support",
    name: "Extrude — Arched Support",
    prompt:
      "Create an arched structural support by sketching two concentric arcs connected by vertical side walls, forming a thick arch profile. Add two mounting holes near the bottom corners and extrude the profile 30 mm.",
  },
  {
    id: "extrude-complex-mounting-plate",
    name: "Extrude — Complex Mounting Plate",
    prompt:
      "Create a complex mounting plate from a single sketch. The outer profile should combine straight edges, chamfered corners, and rounded corners. Add a central slot, four circular mounting holes, and two smaller auxiliary holes. Extrude the entire profile 15 mm.",
  },
];

export const POCKET_PROMPTS = [
  {
    id: "pocket-stepped",
    name: "Pocket — Stepped Cavity",
    prompt:
      "Create a rectangular mechanical block and cut a stepped cavity into its top face. First cut a 40x30 mm pocket 10 mm deep, then cut a smaller 25x15 mm pocket another 8 mm deeper.",
  },
  {
    id: "pocket-tapered",
    name: "Pocket — Tapered Cavity",
    prompt:
      "Create a block with a tapered rectangular cavity. Use two rectangular profiles at different Z heights and loft between them, then subtract the loft from the block.",
  },
  {
    id: "through-slot",
    name: "Cut — Curved Slot",
    prompt:
      "Create a mounting plate with a curved elongated slot. Construct the slot from two concentric arcs connected by straight segments and subtract it completely through the plate.",
  },
];

export const FEATURE_ON_FACE_PROMPTS = [
  {
    id: "face-boss",
    name: "Face — Boss",
    prompt:
      "Create a rectangular base with a sloped top face. Add a cylindrical boss normal to the sloped face, with its axis following the face normal.",
  },
  {
    id: "face-sketch",
    name: "Face — Sketch Placement",
    prompt:
      "Create a rectangular housing, select its vertical side face, create a sketch on that face, and extrude a rectangular mounting boss outward from the face.",
  },
  {
    id: "angled-face-feature",
    name: "Face — Angled Feature",
    prompt:
      "Create a wedge-shaped solid with an angled face. Create a circular sketch on the angled face and extrude a cylindrical boss normal to that face.",
  },
];

export const MULTI_DIRECTION_EXTRUSION_PROMPTS = [
  {
    id: "two-direction-extrude",
    name: "Extrude — Two Directions",
    prompt:
      "Create a central rectangular plate and add an identical boss on both sides along the plate normal. The two bosses should be created by extruding the same profile in opposite directions.",
  },
  {
    id: "offset-extrude",
    name: "Extrude — Offset",
    prompt:
      "Create a base plate and a complex sketch above it. Extrude the sketch downward until it intersects the base, creating an integrated raised feature.",
  },
];

export const BOOLEAN_COMBINATIONS = [
  {
    id: "boolean-housing",
    name: "Boolean — Housing",
    prompt:
      "Create a cylindrical housing by fusing a main cylinder with a smaller mounting boss, then subtract a central bore and four bolt holes.",
  },
  {
    id: "boolean-cross",
    name: "Boolean — Cross-shaped Part",
    prompt:
      "Create two perpendicular rectangular solids, fuse them into a cross-shaped part, then cut a cylindrical hole through the center.",
  },
];

export const TAPERED_FEATURE_PROMPTS = [
  {
    id: "draft-walls",
    name: "Draft — Housing Walls",
    prompt:
      "Create a rectangular open-top housing with 3 mm wall thickness. Apply a 5-degree draft to the four exterior walls while keeping the bottom dimensions fixed.",
  },
  {
    id: "draft-pocket",
    name: "Draft — Molded Pocket",
    prompt:
      "Create a rectangular block with a deep pocket. Apply a 4-degree draft to the pocket walls so the opening is wider than the bottom.",
  },
];

export const FILLET_CHAMFER_WITH_SELECTIVE_EDGE_SELECTION_PROMPTS = [
  {
    id: "selective-fillet",
    name: "Fillet — Selected Edges",
    prompt:
      "Create a rectangular block with four vertical edges. Apply a 5 mm fillet only to the two front vertical edges, leaving the rear edges sharp.",
  },
  {
    id: "mixed-edge-treatment",
    name: "Chamfer + Fillet — Selected",
    prompt:
      "Create a mechanical block with a central hole. Apply a 3 mm fillet to the outer vertical edges and a 1 mm chamfer to the circular hole edges.",
  },
];

export const SYMMETRY_PROMPTS = [
  {
    id: "symmetric-feature-tree",
    name: "Symmetry — Feature Tree",
    prompt:
      "Create a rectangular base with a complex mounting boss on the left side. Mirror the complete boss feature across the central YZ plane. Keep the base as a shared parent feature.",
  },
  {
    id: "symmetric-sketch",
    name: "Sketch — Symmetric Profile",
    prompt:
      "Create a symmetric mechanical bracket using a sketch on the XY plane. Define the left half of the profile and mirror it across the Y axis to create the complete closed profile before extrusion.",
  },
];

export const SHELL_SUBSIQUENT_FEATURES_PROMPTS = [
  {
    id: "shell-boss",
    name: "Shell → Boss",
    prompt:
      "Create a rectangular solid, shell it with 3 mm wall thickness while removing the top face, then create four cylindrical mounting bosses on the interior bottom face.",
  },
  {
    id: "shell-ribs",
    name: "Shell → Ribs",
    prompt:
      "Create a rectangular enclosure, shell it to 2.5 mm wall thickness, remove the top face, then add three internal reinforcement ribs connected to the side walls.",
  },
  {
    id: "shell-flange",
    name: "Shell → Flange",
    prompt:
      "Create a cylindrical housing, shell it with 3 mm wall thickness, then create an external flange around the bottom opening. Add six equally spaced bolt holes to the flange.",
  },
];
