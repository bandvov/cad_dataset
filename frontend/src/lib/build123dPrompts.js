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

export const TRIANGULAR_OVAL_PROMPTS = [
  {
    id: "extrude-triangle",
    name: "Extrude — Triangular Profile",
    prompt:
      "Create a triangular mechanical plate by sketching an equilateral triangular profile on the XY plane and extruding it 15 mm. Add a circular through-hole near the center."
  },

  {
    id: "extrude-asymmetric-triangle",
    name: "Extrude — Asymmetric Triangle",
    prompt:
      "Create a mechanical wedge from an asymmetric triangular profile with three different side lengths. Extrude the profile 40 mm and add two mounting holes near the wider end."
  },

  {
    id: "extrude-rounded-triangle",
    name: "Extrude — Rounded Triangle",
    prompt:
      "Create a rounded triangular plate using three tangent arcs connected by three straight segments. Extrude the closed profile 12 mm and add a central circular through-hole."
  },

  {
    id: "triangle-rib",
    name: "Feature — Triangular Rib",
    prompt:
      "Create a rectangular base plate and add a triangular reinforcement rib along its length. The rib should have a sloped top edge and be fused to the base plate."
  },

  {
    id: "triangle-rib-pattern",
    name: "Pattern — Triangular Ribs",
    prompt:
      "Create a rectangular structural plate with one triangular reinforcement rib. Create a linear pattern of 5 identical ribs across the width with equal spacing."
  },

  {
    id: "triangle-cut",
    name: "Cut — Triangular Pocket",
    prompt:
      "Create a rectangular block and cut a triangular pocket into its top face. The triangular pocket should have two equal sides and be 12 mm deep."
  },

  {
    id: "triangle-through-cut",
    name: "Cut — Triangular Opening",
    prompt:
      "Create a rectangular plate with a triangular through-opening near one end. Use a triangular sketch and subtract it completely through the plate."
  },

  {
    id: "triangle-boss",
    name: "Boss — Triangular",
    prompt:
      "Create a rectangular base and add a raised triangular boss with rounded corners. Extrude the triangular profile 20 mm from the top face."
  },

  {
    id: "triangle-mirror",
    name: "Mirror — Triangular Features",
    prompt:
      "Create a rectangular plate with a triangular mounting boss on the left side. Mirror the triangular boss across the central YZ plane to create a symmetric pair."
  },

  {
    id: "triangle-circular-pattern",
    name: "Pattern — Triangular Features",
    prompt:
      "Create a circular base with one triangular reinforcement feature near its outer edge. Circular-pattern the triangular feature 6 times around the central Z axis."
  },

  {
    id: "oval-profile",
    name: "Extrude — Oval Profile",
    prompt:
      "Create an oval mechanical plate by sketching an ellipse with a major axis of 80 mm and minor axis of 40 mm. Extrude it 12 mm and add a centered circular through-hole."
  },

  {
    id: "oval-hole",
    name: "Cut — Oval Hole",
    prompt:
      "Create a rectangular mounting plate and cut an elongated oval through-hole through the center. The opening should have a major axis of 60 mm and minor axis of 20 mm."
  },

  {
    id: "oval-boss",
    name: "Boss — Oval",
    prompt:
      "Create a rectangular base plate and add an oval-shaped raised boss on its top face. The boss should be 60 mm long, 30 mm wide, and 10 mm high."
  },

  {
    id: "oval-pocket",
    name: "Pocket — Oval Cavity",
    prompt:
      "Create a rectangular block with a deep oval pocket on the top face. The pocket should have a 70 mm major axis, 35 mm minor axis, and 15 mm depth."
  },

  {
    id: "concentric-oval",
    name: "Sketch — Concentric Ovals",
    prompt:
      "Create an oval ring by sketching two concentric ellipses with different major and minor axes. Extrude the region between them 15 mm to create an oval-shaped ring."
  },

  {
    id: "oval-flange",
    name: "Multi-step — Oval Flange",
    prompt:
      "Create an oval flange in multiple steps: extrude an oval base profile, add a smaller raised oval boss, cut a central oval opening, then create four circular mounting holes near the outer perimeter."
  },

  {
    id: "oval-pattern",
    name: "Pattern — Oval Slots",
    prompt:
      "Create a rectangular mounting plate with one elongated oval slot. Create a linear pattern of 4 identical oval slots along the X axis with 20 mm spacing."
  },

  {
    id: "oval-mirror",
    name: "Mirror — Oval Bosses",
    prompt:
      "Create a rectangular plate with an oval boss near the left side. Mirror the complete oval boss feature across the YZ plane to create an identical boss on the right side."
  },

  {
    id: "oval-loft",
    name: "Loft — Oval Transition",
    prompt:
      "Create a tapered transition using three oval profiles at different Z heights. Start with an 80x40 mm ellipse, transition to a 60x30 mm ellipse, and finish with a 40x20 mm ellipse."
  },

  {
    id: "triangle-to-oval-loft",
    name: "Loft — Triangle to Oval",
    prompt:
      "Create a complex transition by lofting from a triangular profile at z=0 to an oval profile at z=50. Keep both profiles centered on the same Z axis and create a smooth solid transition."
  },

  {
    id: "oval-sweep",
    name: "Sweep — Oval Profile",
    prompt:
      "Create a curved duct by sweeping an oval profile along an S-shaped 3D path. Use an ellipse with a 30 mm major axis and 15 mm minor axis as the sweep profile."
  },

  {
    id: "triangle-loft",
    name: "Loft — Triangular Profiles",
    prompt:
      "Create a tapered triangular structure by lofting between three triangular profiles at different Z heights. The bottom triangle should be 60 mm wide, the middle 45 mm wide, and the top 25 mm wide."
  },

  {
    id: "triangle-to-circle",
    name: "Loft — Triangle to Circle",
    prompt:
      "Create a transition duct by lofting from a 60 mm wide triangular profile at the bottom to a 30 mm diameter circular profile at the top."
  },

  {
    id: "oval-revolve",
    name: "Revolve — Oval-derived Profile",
    prompt:
      "Create a rotational mechanical component using a cross-section containing curved and elliptical-style geometry, then revolve the profile 360 degrees around the Z axis. Add a central bore afterward."
  },

  {
    id: "oval-bolt-pattern",
    name: "Oval Flange — Bolt Pattern",
    prompt:
      "Create an oval flange with a central oval opening. Add one circular mounting hole near one end and create a mirrored pair at both ends. Add another pair along the opposite side."
  },

  {
    id: "triangle-slot-pattern",
    name: "Pattern — Triangular Slots",
    prompt:
      "Create a rectangular plate with one triangular through-slot having rounded corners. Create a linear pattern of 4 identical slots along the X axis."
  },

  {
    id: "triangle-oval-bracket",
    name: "Complex — Triangle + Oval",
    prompt:
      "Create a mounting bracket from a complex triangular outer profile with rounded corners. Add an oval through-hole near the center, two circular mounting holes near the base, and a triangular reinforcement rib on the rear."
  },

  {
    id: "triangle-oval-flange",
    name: "Complex — Triangular Oval Flange",
    prompt:
      "Create a multi-step mounting flange with a rounded triangular outer profile and an oval central opening. Add a raised oval boss, four circular mounting holes, and triangular reinforcement ribs on three sides."
  },
];

export const ADVANCED_PROFILE_PROMPTS = [
  {
    id: "trapezoid-extrusion",
    name: "Extrude — Trapezoidal Profile",
    prompt:
      "Create a mechanical part from a trapezoidal sketch with a 70 mm bottom edge, 40 mm top edge, and 45 mm height. Extrude the profile 25 mm and add two circular mounting holes near the wider edge."
  },

  {
    id: "asymmetric-trapezoid",
    name: "Extrude — Asymmetric Trapezoid",
    prompt:
      "Create a solid from an asymmetric trapezoidal profile. The profile should have four unequal sides and one angled side steeper than the other. Extrude it 35 mm and add a through-hole near the center."
  },

  {
    id: "trapezoid-pocket",
    name: "Pocket — Trapezoidal",
    prompt:
      "Create a rectangular block and cut a trapezoidal pocket into the top face. The pocket should be 15 mm deep with the wider side at the opening."
  },

  {
    id: "trapezoid-rib",
    name: "Feature — Trapezoidal Rib",
    prompt:
      "Create a rectangular base plate and add a trapezoidal reinforcement rib. The rib should have a wide base, narrower top, and sloped side walls."
  },

  {
    id: "pentagon-extrusion",
    name: "Extrude — Pentagon",
    prompt:
      "Create a regular pentagonal plate by sketching a five-sided polygon and extruding it 15 mm. Add a central circular through-hole."
  },

  {
    id: "irregular-pentagon",
    name: "Extrude — Irregular Pentagon",
    prompt:
      "Create a mechanical mounting plate from an irregular five-sided profile with different edge lengths. Extrude it 20 mm and add three circular mounting holes."
  },

  {
    id: "pentagon-pocket",
    name: "Pocket — Pentagon",
    prompt:
      "Create a solid block and subtract a regular pentagonal pocket from its top face. The pocket should be 12 mm deep."
  },

  {
    id: "hexagon-extrusion",
    name: "Extrude — Hexagonal Profile",
    prompt:
      "Create a hexagonal mechanical plate using a regular hexagonal sketch and extrude it 20 mm. Add a central circular bore and six smaller mounting holes around it."
  },

  {
    id: "hexagonal-boss",
    name: "Boss — Hexagonal",
    prompt:
      "Create a rectangular base plate with a raised hexagonal boss on its top face. Extrude the hexagonal boss 15 mm and cut a circular through-hole through its center."
  },

  {
    id: "hexagonal-pattern",
    name: "Pattern — Hexagonal Bosses",
    prompt:
      "Create a circular plate with one hexagonal mounting boss near its perimeter. Circular-pattern the boss 6 times around the central axis."
  },

  {
    id: "hexagonal-pocket",
    name: "Pocket — Hexagonal",
    prompt:
      "Create a cylindrical block and cut a hexagonal pocket into its top face. The pocket should be 10 mm deep and centered on the cylinder."
  },

  {
    id: "star-extrusion",
    name: "Extrude — Star Profile",
    prompt:
      "Create a five-point star-shaped plate using a sketch with alternating outer and inner vertices. Extrude it 10 mm and add a central circular hole."
  },

  {
    id: "star-pocket",
    name: "Pocket — Star",
    prompt:
      "Create a rectangular block and subtract a five-point star-shaped pocket from its top face. The pocket should be 8 mm deep."
  },

  {
    id: "star-boss",
    name: "Boss — Star-shaped",
    prompt:
      "Create a circular base and add a raised five-point star-shaped boss on the top face. Extrude the star 12 mm."
  },

  {
    id: "six-point-star",
    name: "Extrude — Six-point Star",
    prompt:
      "Create a six-point star profile from twelve alternating inner and outer vertices and extrude it 15 mm. Add a circular through-hole at the center."
  },

  {
    id: "arc-profile",
    name: "Extrude — Arc-based Profile",
    prompt:
      "Create a mechanical plate from a closed profile containing two large tangent arcs connected by straight segments. Extrude the profile 20 mm and add two mounting holes."
  },

  {
    id: "multi-radius-profile",
    name: "Extrude — Multi-radius Profile",
    prompt:
      "Create a closed mechanical profile using four straight segments and four arcs with different radii. The profile should have rounded corners of varying sizes. Extrude it 25 mm."
  },

  {
    id: "semicircle-profile",
    name: "Extrude — Semicircular Profile",
    prompt:
      "Create a D-shaped mechanical plate using a rectangle connected to a semicircular end. Extrude the profile 15 mm and add two circular mounting holes."
  },

  {
    id: "double-arc-profile",
    name: "Extrude — Double Arc",
    prompt:
      "Create a long curved mounting plate using two concentric arcs connected at both ends. Extrude the resulting curved ring profile 12 mm and add four mounting holes."
  },

  {
    id: "keyhole-profile",
    name: "Extrude — Keyhole Profile",
    prompt:
      "Create a keyhole-shaped plate consisting of a circular region connected to a narrow rectangular neck. Extrude the combined profile 15 mm and add a small through-hole in the rectangular section."
  },

  {
    id: "shield-profile",
    name: "Extrude — Shield Profile",
    prompt:
      "Create a shield-shaped mechanical plate using straight upper edges, angled side edges, and a pointed bottom. Extrude it 18 mm and add two circular mounting holes near the top."
  },

  {
    id: "arrow-profile",
    name: "Extrude — Arrow Profile",
    prompt:
      "Create an arrow-shaped plate using a rectangular shaft and two angled edges forming the arrowhead. Extrude the complete closed profile 12 mm."
  },

  {
    id: "cross-profile",
    name: "Extrude — Cross Profile",
    prompt:
      "Create a cross-shaped plate from a single closed sketch consisting of multiple horizontal and vertical segments. Extrude it 15 mm and add a central circular hole."
  },

  {
    id: "plus-with-holes",
    name: "Extrude — Cross with Holes",
    prompt:
      "Create a plus-shaped mechanical plate and add one circular hole at the end of each of its four arms. Extrude the complete profile 10 mm."
  },

  {
    id: "octagon-profile",
    name: "Extrude — Octagonal Profile",
    prompt:
      "Create an octagonal mounting plate by sketching an eight-sided profile with chamfered corners. Extrude it 20 mm and add a central bore plus four mounting holes."
  },

  {
    id: "octagon-pocket",
    name: "Pocket — Octagonal",
    prompt:
      "Create a rectangular block with a centered octagonal pocket. Cut the pocket 12 mm deep and add a smaller circular through-hole at its bottom."
  },

  {
    id: "irregular-polygon",
    name: "Extrude — Irregular Polygon",
    prompt:
      "Create a complex mechanical plate from an irregular seven-sided polygon. Use different edge lengths and several angled edges. Extrude it 20 mm and add three circular mounting holes."
  },

  {
    id: "polygon-with-slot",
    name: "Extrude — Polygon + Slot",
    prompt:
      "Create an irregular hexagonal mounting plate containing a centered elongated slot and four circular mounting holes. Extrude the entire sketch 15 mm."
  },

  {
    id: "polygon-boss-pattern",
    name: "Pattern — Polygon Boss",
    prompt:
      "Create a circular base with one pentagonal boss positioned near the outer edge. Circular-pattern the pentagonal boss 5 times around the center."
  },

  {
    id: "mixed-arc-polygon",
    name: "Extrude — Mixed Arc Polygon",
    prompt:
      "Create a complex closed sketch combining straight edges, a semicircle, two tangent arcs, and angled edges. Extrude the resulting profile 25 mm."
  },

  {
    id: "rounded-hexagon",
    name: "Extrude — Rounded Hexagon",
    prompt:
      "Create a rounded hexagonal plate where each corner is replaced by a tangent arc. Extrude the profile 15 mm and add a central circular bore."
  },

  {
    id: "triangle-hexagon-loft",
    name: "Loft — Triangle to Hexagon",
    prompt:
      "Create a solid loft between a triangular profile at z=0, a pentagonal profile at z=30, and a hexagonal profile at z=60. Keep all profiles centered on the same vertical axis."
  },

  {
    id: "star-to-circle-loft",
    name: "Loft — Star to Circle",
    prompt:
      "Create a smooth transition by lofting from a five-point star profile at z=0 to a circular profile with 30 mm diameter at z=50."
  },

  {
    id: "trapezoid-to-oval-loft",
    name: "Loft — Trapezoid to Oval",
    prompt:
      "Create a transition body by lofting from a 60 mm wide trapezoidal profile at z=0 to an oval profile measuring 40x20 mm at z=50."
  },

  {
    id: "polygon-sweep",
    name: "Sweep — Polygon Profile",
    prompt:
      "Sweep a regular hexagonal profile along a curved 3D path consisting of straight segments and two tangent arcs. Create a continuous solid pipe-like structure."
  },

  {
    id: "triangle-sweep",
    name: "Sweep — Triangular Profile",
    prompt:
      "Sweep a triangular profile along an S-shaped path. Keep the triangular profile oriented perpendicular to the path and create a continuous curved structural member."
  },

  {
    id: "oval-sweep-pattern",
    name: "Sweep — Oval + Pattern",
    prompt:
      "Sweep an oval profile along a curved path to create a tubular feature, then create three translated copies using a linear pattern."
  },

  {
    id: "complex-profile-mirror",
    name: "Mirror — Complex Profile",
    prompt:
      "Create an asymmetric profile containing arcs, angled edges, and a triangular section. Extrude it to form a mounting feature, then mirror the complete feature across the central YZ plane."
  },

  {
    id: "complex-profile-pattern",
    name: "Pattern — Complex Profile",
    prompt:
      "Create one irregular polygonal mounting boss containing a circular hole and a triangular reinforcement. Circular-pattern the complete feature 6 times around the center."
  },

  {
    id: "flange-polygon",
    name: "Multi-step — Polygon Flange",
    prompt:
      "Create a flange with an octagonal outer profile and circular center bore. Add a raised cylindrical boss, cut the bore through the boss, create one mounting hole, circular-pattern it 6 times, and chamfer the outer edges."
  },

  {
    id: "complex-profile-bracket",
    name: "Multi-step — Polygon Bracket",
    prompt:
      "Create a mounting bracket from an irregular pentagonal profile. Extrude the profile, add a triangular reinforcement rib, mirror the rib, cut an oval slot, create two circular mounting holes, and finish the outer edges with fillets."
  },

  {
    id: "complex-multi-profile",
    name: "Complex — Multiple Profiles",
    prompt:
      "Create a mechanical component using multiple profile types: an octagonal base, a raised oval boss, a triangular reinforcement rib, and a pentagonal mounting feature. Add circular holes and fillet the external edges."
  },
];