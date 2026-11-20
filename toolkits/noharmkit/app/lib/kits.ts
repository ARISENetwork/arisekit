export type Kit = {
  id: string;
  name: string;
  description: string;
  formats: readonly string[];
  image: string;
  clip?: string;
  link?: { label: string; href: string };
  comingSoon?: boolean;
};

export const ESTABLISHED_KITS: readonly Kit[] = [
  {
    id: "sct",
    name: "SCTKit",
    description: "Measure how judgments shift with new, uncertain information, compared with an expert panel.",
    formats: ["MCQ"],
    image: "/kits/sctbench-poster.jpg",
    clip: "/kits/sctbench.mp4",
    link: { label: "Paper", href: "https://ai.nejm.org/doi/full/10.1056/AIdbp2500120" },
  },
  {
    id: "cpc",
    name: "CPCKit",
    description: "Build diagnostic reasoning benchmarks from complex cases, starting with staged differentials.",
    formats: ["MCQ", "Open-ended"],
    image: "/kits/cpcbench.jpg",
    link: { label: "Paper", href: "https://arxiv.org/abs/2509.12194" },
  },
  {
    id: "medagentbench",
    name: "MedAgentKit",
    description: "Test AI agents on multi-step tasks in a simulated electronic health record.",
    formats: ["Agentic"],
    image: "/kits/medagentbench-poster.jpg",
    clip: "/kits/medagentbench.mp4",
    link: { label: "Paper", href: "https://psb.stanford.edu/psb-online/proceedings/psb26/chen_eric.pdf" },
  },
  {
    id: "rexrank",
    name: "RadiologyKit",
    description: "Evaluate AI-generated chest X-ray reports against reference reports.",
    formats: ["Open-ended"],
    image: "/kits/rexrank-mini-poster.jpg",
    clip: "/kits/rexrank-mini.mp4",
    link: { label: "Website", href: "https://rexrank.ai/" },
  },
  {
    id: "multiturn",
    name: "MultiturnKit",
    description: "Evaluate AI across multi-turn medical conversations.",
    formats: ["Open-ended"],
    image: "/kits/multiturn.jpg",
    comingSoon: true,
  },
  {
    id: "health-agent",
    name: "PhysicianBenchKit",
    description: "Test AI agents on long-horizon physician tasks in an electronic health record.",
    formats: ["Agentic"],
    image: "/kits/physicianbench-poster.jpg",
    clip: "/kits/physicianbench.mp4",
    comingSoon: true,
  },
];

export const GUIDED_ASSISTANT: Kit = {
  id: "custom",
  name: "Guided assistant",
  description: "Describe your idea and get guided to the right custom design.",
  formats: [],
  image: "/kits/guided.jpg",
};
