"""
Generates high-quality SVG diagrams for Folio demo documents in src/frontend/assets/demo/.
"""
from pathlib import Path

OUT_DIR = Path("src/frontend/assets/demo")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DIAGRAMS = {}

DIAGRAMS["neural_network_architecture.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="nodeInput" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="100%" stop-color="#0284c7" />
    </linearGradient>
    <linearGradient id="nodeHidden1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#a855f7" />
      <stop offset="100%" stop-color="#7e22ce" />
    </linearGradient>
    <linearGradient id="nodeHidden2" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ec4899" />
      <stop offset="100%" stop-color="#be185d" />
    </linearGradient>
    <linearGradient id="nodeOutput" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10b981" />
      <stop offset="100%" stop-color="#047857" />
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#bg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="42" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Deep Feedforward Neural Network Architecture</text>
  <text x="400" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Multilayer Perceptron (MLP) with Forward Propagation &amp; Activation Mapping</text>

  <!-- Layer Labels -->
  <text x="140" y="395" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="600" fill="#38bdf8" text-anchor="middle">Input Layer</text>
  <text x="140" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="middle">x ∈ ℝ³</text>

  <text x="310" y="395" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="600" fill="#c084fc" text-anchor="middle">Hidden Layer 1</text>
  <text x="310" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="middle">h⁽¹⁾ = σ(W⁽¹⁾x + b⁽¹⁾)</text>

  <text x="490" y="395" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="600" fill="#f472b6" text-anchor="middle">Hidden Layer 2</text>
  <text x="490" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="middle">h⁽²⁾ = σ(W⁽²⁾h⁽¹⁾ + b⁽²⁾)</text>

  <text x="660" y="395" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="600" fill="#34d399" text-anchor="middle">Output Layer</text>
  <text x="660" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="middle">ŷ = softmax(W⁽³⁾h⁽²⁾ + b⁽³⁾)</text>

  <!-- Synaptic Connections (Lines) -->
  <!-- Layer 1 to Layer 2 -->
  <g stroke="#334155" stroke-width="1.2" opacity="0.65">
    <line x1="140" y1="160" x2="310" y2="120" /><line x1="140" y1="160" x2="310" y2="190" /><line x1="140" y1="160" x2="310" y2="260" /><line x1="140" y1="160" x2="310" y2="330" />
    <line x1="140" y1="240" x2="310" y2="120" /><line x1="140" y1="240" x2="310" y2="190" /><line x1="140" y1="240" x2="310" y2="260" /><line x1="140" y1="240" x2="310" y2="330" />
    <line x1="140" y1="320" x2="310" y2="120" /><line x1="140" y1="320" x2="310" y2="190" /><line x1="140" y1="320" x2="310" y2="260" /><line x1="140" y1="320" x2="310" y2="330" />
    <!-- Layer 2 to Layer 3 -->
    <line x1="310" y1="120" x2="490" y2="120" /><line x1="310" y1="120" x2="490" y2="190" /><line x1="310" y1="120" x2="490" y2="260" /><line x1="310" y1="120" x2="490" y2="330" />
    <line x1="310" y1="190" x2="490" y2="120" /><line x1="310" y1="190" x2="490" y2="190" /><line x1="310" y1="190" x2="490" y2="260" /><line x1="310" y1="190" x2="490" y2="330" />
    <line x1="310" y1="260" x2="490" y2="120" /><line x1="310" y1="260" x2="490" y2="190" /><line x1="310" y1="260" x2="490" y2="260" /><line x1="310" y1="260" x2="490" y2="330" />
    <line x1="310" y1="330" x2="490" y2="120" /><line x1="310" y1="330" x2="490" y2="190" /><line x1="310" y1="330" x2="490" y2="260" /><line x1="310" y1="330" x2="490" y2="330" />
    <!-- Layer 3 to Output -->
    <line x1="490" y1="120" x2="660" y2="195" /><line x1="490" y1="120" x2="660" y2="275" />
    <line x1="490" y1="190" x2="660" y2="195" /><line x1="490" y1="190" x2="660" y2="275" />
    <line x1="490" y1="260" x2="660" y2="195" /><line x1="490" y1="260" x2="660" y2="275" />
    <line x1="490" y1="330" x2="660" y2="195" /><line x1="490" y1="330" x2="660" y2="275" />
  </g>

  <!-- Input Nodes -->
  <circle cx="140" cy="160" r="18" fill="url(#nodeInput)" filter="url(#glow)" stroke="#0369a1" stroke-width="2" />
  <text x="140" y="165" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#ffffff" text-anchor="middle">x₁</text>

  <circle cx="140" cy="240" r="18" fill="url(#nodeInput)" filter="url(#glow)" stroke="#0369a1" stroke-width="2" />
  <text x="140" y="245" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#ffffff" text-anchor="middle">x₂</text>

  <circle cx="140" cy="320" r="18" fill="url(#nodeInput)" filter="url(#glow)" stroke="#0369a1" stroke-width="2" />
  <text x="140" y="325" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#ffffff" text-anchor="middle">x₃</text>

  <!-- Hidden Layer 1 Nodes -->
  <circle cx="310" cy="120" r="17" fill="url(#nodeHidden1)" filter="url(#glow)" stroke="#6b21a8" stroke-width="2" />
  <text x="310" y="125" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₁⁽¹⁾</text>

  <circle cx="310" cy="190" r="17" fill="url(#nodeHidden1)" filter="url(#glow)" stroke="#6b21a8" stroke-width="2" />
  <text x="310" y="195" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₂⁽¹⁾</text>

  <circle cx="310" cy="260" r="17" fill="url(#nodeHidden1)" filter="url(#glow)" stroke="#6b21a8" stroke-width="2" />
  <text x="310" y="265" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₃⁽¹⁾</text>

  <circle cx="310" cy="330" r="17" fill="url(#nodeHidden1)" filter="url(#glow)" stroke="#6b21a8" stroke-width="2" />
  <text x="310" y="335" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₄⁽¹⁾</text>

  <!-- Hidden Layer 2 Nodes -->
  <circle cx="490" cy="120" r="17" fill="url(#nodeHidden2)" filter="url(#glow)" stroke="#9d174d" stroke-width="2" />
  <text x="490" y="125" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₁⁽²⁾</text>

  <circle cx="490" cy="190" r="17" fill="url(#nodeHidden2)" filter="url(#glow)" stroke="#9d174d" stroke-width="2" />
  <text x="490" y="195" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₂⁽²⁾</text>

  <circle cx="490" cy="260" r="17" fill="url(#nodeHidden2)" filter="url(#glow)" stroke="#9d174d" stroke-width="2" />
  <text x="490" y="265" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₃⁽²⁾</text>

  <circle cx="490" cy="330" r="17" fill="url(#nodeHidden2)" filter="url(#glow)" stroke="#9d174d" stroke-width="2" />
  <text x="490" y="335" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#ffffff" text-anchor="middle">h₄⁽²⁾</text>

  <!-- Output Nodes -->
  <circle cx="660" cy="195" r="18" fill="url(#nodeOutput)" filter="url(#glow)" stroke="#065f46" stroke-width="2" />
  <text x="660" y="200" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#ffffff" text-anchor="middle">ŷ₁</text>

  <circle cx="660" cy="275" r="18" fill="url(#nodeOutput)" filter="url(#glow)" stroke="#065f46" stroke-width="2" />
  <text x="660" y="280" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#ffffff" text-anchor="middle">ŷ₂</text>
</svg>
"""

DIAGRAMS["transformer_attention.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="tbg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#090d16" />
      <stop offset="100%" stop-color="#1e1e38" />
    </linearGradient>
    <linearGradient id="gradQ" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f59e0b" />
      <stop offset="100%" stop-color="#b45309" />
    </linearGradient>
    <linearGradient id="gradK" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#3b82f6" />
      <stop offset="100%" stop-color="#1d4ed8" />
    </linearGradient>
    <linearGradient id="gradV" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10b981" />
      <stop offset="100%" stop-color="#047857" />
    </linearGradient>
    <linearGradient id="gradBlock" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#334155" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#tbg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#475569" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="42" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Scaled Dot-Product Attention &amp; Multi-Head Structure</text>
  <text x="400" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Attention(Q, K, V) = softmax(QKᵀ / √dₖ) V</text>

  <!-- Left: Single Attention Head Flow -->
  <rect x="60" y="90" width="320" height="330" rx="10" fill="#131b2e" stroke="#2563eb" stroke-dasharray="4,4" stroke-width="1.5" />
  <text x="220" y="115" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#60a5fa" text-anchor="middle">Scaled Dot-Product Attention Core</text>

  <!-- Input Q, K, V boxes at bottom of core -->
  <rect x="80" y="360" width="60" height="36" rx="6" fill="url(#gradQ)" />
  <text x="110" y="383" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">Q</text>

  <rect x="190" y="360" width="60" height="36" rx="6" fill="url(#gradK)" />
  <text x="220" y="383" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">K</text>

  <rect x="300" y="360" width="60" height="36" rx="6" fill="url(#gradV)" />
  <text x="330" y="383" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">V</text>

  <!-- MatMul QK^T -->
  <rect x="120" y="295" width="120" height="34" rx="6" fill="url(#gradBlock)" stroke="#64748b" />
  <text x="180" y="317" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="600" fill="#e2e8f0" text-anchor="middle">MatMul (Q · Kᵀ)</text>

  <!-- Scale -->
  <rect x="120" y="240" width="120" height="30" rx="6" fill="url(#gradBlock)" stroke="#64748b" />
  <text x="180" y="260" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#cbd5e1" text-anchor="middle">Scale (÷ √dₖ)</text>

  <!-- Softmax -->
  <rect x="120" y="185" width="120" height="30" rx="6" fill="url(#gradBlock)" stroke="#a855f7" stroke-width="1.5" />
  <text x="180" y="205" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#c084fc" text-anchor="middle">Softmax</text>

  <!-- MatMul with V -->
  <rect x="150" y="130" width="140" height="34" rx="6" fill="url(#gradBlock)" stroke="#10b981" stroke-width="1.5" />
  <text x="220" y="152" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#34d399" text-anchor="middle">MatMul (Weights · V)</text>

  <!-- Flow Arrows left -->
  <g stroke="#94a3b8" stroke-width="1.5" fill="none">
    <path d="M 110 360 L 110 340 L 160 340 L 160 330" />
    <path d="M 220 360 L 220 330" />
    <path d="M 180 295 L 180 270" />
    <path d="M 180 240 L 180 215" />
    <path d="M 180 185 L 180 170 L 200 170 L 200 165" />
    <path d="M 330 360 L 330 147 L 290 147" />
  </g>

  <!-- Right: Multi-Head Composition -->
  <rect x="420" y="90" width="320" height="330" rx="10" fill="#131b2e" stroke="#8b5cf6" stroke-width="1.5" />
  <text x="580" y="115" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#a78bfa" text-anchor="middle">Multi-Head Attention (h = 8)</text>

  <!-- Stacked Heads -->
  <rect x="445" y="270" width="70" height="60" rx="6" fill="#312e81" stroke="#6366f1" stroke-width="1" />
  <text x="480" y="305" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#c7d2fe" text-anchor="middle">Head 1</text>

  <rect x="525" y="270" width="70" height="60" rx="6" fill="#312e81" stroke="#6366f1" stroke-width="1" />
  <text x="560" y="305" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#c7d2fe" text-anchor="middle">Head 2</text>

  <text x="610" y="305" font-family="monospace" font-size="14" fill="#a5b4fc" text-anchor="middle">···</text>

  <rect x="635" y="270" width="80" height="60" rx="6" fill="#312e81" stroke="#6366f1" stroke-width="1" />
  <text x="675" y="305" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#c7d2fe" text-anchor="middle">Head h</text>

  <!-- Concat Block -->
  <rect x="460" y="200" width="240" height="36" rx="6" fill="url(#gradBlock)" stroke="#8b5cf6" stroke-width="1.5" />
  <text x="580" y="223" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#e2e8f0" text-anchor="middle">Concat(head₁, ..., headₕ)</text>

  <!-- Linear Projection W^O -->
  <rect x="480" y="135" width="200" height="36" rx="6" fill="url(#gradBlock)" stroke="#38bdf8" stroke-width="1.5" />
  <text x="580" y="158" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#38bdf8" text-anchor="middle">Linear Projection (Wᴼ)</text>

  <!-- Flow arrows right -->
  <g stroke="#94a3b8" stroke-width="1.5" fill="none">
    <path d="M 480 270 L 480 236" />
    <path d="M 560 270 L 560 236" />
    <path d="M 675 270 L 675 236" />
    <path d="M 580 200 L 580 171" />
    <path d="M 580 135 L 580 115" stroke-dasharray="2,2" />
  </g>

  <!-- Bottom annotation -->
  <text x="580" y="380" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Allows model to jointly attend to information</text>
  <text x="580" y="398" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">at different positions from diverse representation subspaces.</text>
</svg>
"""

DIAGRAMS["binary_search_tree.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="bstBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="nodeRoot" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="100%" stop-color="#0284c7" />
    </linearGradient>
    <linearGradient id="nodeInner" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#818cf8" />
      <stop offset="100%" stop-color="#4f46e5" />
    </linearGradient>
    <linearGradient id="nodeLeaf" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#34d399" />
      <stop offset="100%" stop-color="#059669" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#bstBg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="42" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Binary Search Tree (BST) Node Invariant &amp; Hierarchy</text>
  <text x="400" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Invariant: key(left) &lt; key(node) &lt; key(right) — Average Search Complexity: O(log n)</text>

  <!-- Edges -->
  <g stroke="#475569" stroke-width="2">
    <!-- Root to Level 1 -->
    <line x1="400" y1="120" x2="240" y2="200" />
    <line x1="400" y1="120" x2="560" y2="200" />

    <!-- Level 1 to Level 2 -->
    <line x1="240" y1="200" x2="150" y2="290" />
    <line x1="240" y1="200" x2="320" y2="290" />
    <line x1="560" y1="200" x2="480" y2="290" />
    <line x1="560" y1="200" x2="650" y2="290" />

    <!-- Level 2 to Leaves -->
    <line x1="150" y1="290" x2="100" y2="370" stroke-dasharray="3,3" />
    <line x1="320" y1="290" x2="360" y2="370" stroke-dasharray="3,3" />
    <line x1="650" y1="290" x2="700" y2="370" stroke-dasharray="3,3" />
  </g>

  <!-- Edge comparison badges -->
  <rect x="290" y="145" width="48" height="20" rx="4" fill="#1e293b" stroke="#38bdf8" />
  <text x="314" y="159" font-family="monospace" font-size="11" fill="#38bdf8" text-anchor="middle">&lt; 50</text>

  <rect x="465" y="145" width="48" height="20" rx="4" fill="#1e293b" stroke="#38bdf8" />
  <text x="489" y="159" font-family="monospace" font-size="11" fill="#38bdf8" text-anchor="middle">&gt; 50</text>

  <!-- Root Node (50) -->
  <circle cx="400" cy="120" r="26" fill="url(#nodeRoot)" stroke="#bae6fd" stroke-width="2" />
  <text x="400" y="127" font-family="monospace" font-size="16" font-weight="700" fill="#fff" text-anchor="middle">50</text>
  <text x="400" y="85" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#38bdf8" text-anchor="middle">Root Node</text>

  <!-- Level 1 Nodes -->
  <circle cx="240" cy="200" r="24" fill="url(#nodeInner)" stroke="#c7d2fe" stroke-width="2" />
  <text x="240" y="207" font-family="monospace" font-size="15" font-weight="700" fill="#fff" text-anchor="middle">25</text>

  <circle cx="560" cy="200" r="24" fill="url(#nodeInner)" stroke="#c7d2fe" stroke-width="2" />
  <text x="560" y="207" font-family="monospace" font-size="15" font-weight="700" fill="#fff" text-anchor="middle">75</text>

  <!-- Level 2 Nodes -->
  <circle cx="150" cy="290" r="22" fill="url(#nodeInner)" stroke="#c7d2fe" stroke-width="1.5" />
  <text x="150" y="296" font-family="monospace" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">12</text>

  <circle cx="320" cy="290" r="22" fill="url(#nodeInner)" stroke="#c7d2fe" stroke-width="1.5" />
  <text x="320" y="296" font-family="monospace" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">38</text>

  <circle cx="480" cy="290" r="22" fill="url(#nodeInner)" stroke="#c7d2fe" stroke-width="1.5" />
  <text x="480" y="296" font-family="monospace" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">62</text>

  <circle cx="650" cy="290" r="22" fill="url(#nodeInner)" stroke="#c7d2fe" stroke-width="1.5" />
  <text x="650" y="296" font-family="monospace" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">88</text>

  <!-- Level 3 Leaves -->
  <circle cx="100" cy="370" r="20" fill="url(#nodeLeaf)" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="100" y="376" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">5</text>

  <circle cx="360" cy="370" r="20" fill="url(#nodeLeaf)" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="360" y="376" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">45</text>

  <circle cx="700" cy="370" r="20" fill="url(#nodeLeaf)" stroke="#a7f3d0" stroke-width="1.5" />
  <text x="700" y="376" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">95</text>

  <!-- In-Order Traversal Trajectory Note -->
  <rect x="220" y="412" width="360" height="26" rx="6" fill="#0f172a" stroke="#64748b" />
  <text x="400" y="429" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">In-order traversal visits keys in ascending sorted order: 5 → 12 → 25 → 38 → 45 → 50 ...</text>
</svg>
"""

DIAGRAMS["b_tree_indexing.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="btBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="nodeBlock" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e293b" />
      <stop offset="100%" stop-color="#0f172a" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#btBg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="40" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">B-Tree Database Index Structure (Order m = 4)</text>
  <text x="400" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Balanced Multi-Way Search Index Optimized for Block Storage &amp; Sequential Disk Reads</text>

  <!-- Level 0: Root Page -->
  <g transform="translate(300, 90)">
    <rect width="200" height="46" rx="6" fill="#1e293b" stroke="#38bdf8" stroke-width="2" />
    <line x1="50" y1="0" x2="50" y2="46" stroke="#475569" />
    <line x1="100" y1="0" x2="100" y2="46" stroke="#475569" />
    <line x1="150" y1="0" x2="150" y2="46" stroke="#475569" />
    <!-- Pointers (dots) & Keys -->
    <circle cx="25" cy="23" r="5" fill="#38bdf8" />
    <text x="75" y="28" font-family="monospace" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">30</text>
    <circle cx="125" cy="23" r="5" fill="#38bdf8" />
    <text x="175" y="28" font-family="monospace" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">70</text>
    <text x="100" y="-10" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#38bdf8" text-anchor="middle">Root Index Node</text>
  </g>

  <!-- Pointers branching from root -->
  <g stroke="#38bdf8" stroke-width="1.5" fill="none">
    <path d="M 325 136 L 160 210" />
    <path d="M 425 136 L 400 210" />
    <path d="M 475 136 L 640 210" />
  </g>

  <!-- Level 1: Internal Nodes -->
  <!-- Left Internal Node -->
  <g transform="translate(60, 210)">
    <rect width="200" height="42" rx="6" fill="#1e293b" stroke="#818cf8" stroke-width="1.5" />
    <line x1="50" y1="0" x2="50" y2="42" stroke="#475569" />
    <line x1="100" y1="0" x2="100" y2="42" stroke="#475569" />
    <line x1="150" y1="0" x2="150" y2="42" stroke="#475569" />
    <circle cx="25" cy="21" r="4" fill="#818cf8" />
    <text x="75" y="26" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">10</text>
    <circle cx="125" cy="21" r="4" fill="#818cf8" />
    <text x="175" y="26" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">20</text>
  </g>

  <!-- Middle Internal Node -->
  <g transform="translate(300, 210)">
    <rect width="200" height="42" rx="6" fill="#1e293b" stroke="#818cf8" stroke-width="1.5" />
    <line x1="50" y1="0" x2="50" y2="42" stroke="#475569" />
    <line x1="100" y1="0" x2="100" y2="42" stroke="#475569" />
    <line x1="150" y1="0" x2="150" y2="42" stroke="#475569" />
    <circle cx="25" cy="21" r="4" fill="#818cf8" />
    <text x="75" y="26" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">45</text>
    <circle cx="125" cy="21" r="4" fill="#818cf8" />
    <text x="175" y="26" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">58</text>
  </g>

  <!-- Right Internal Node -->
  <g transform="translate(540, 210)">
    <rect width="200" height="42" rx="6" fill="#1e293b" stroke="#818cf8" stroke-width="1.5" />
    <line x1="50" y1="0" x2="50" y2="42" stroke="#475569" />
    <line x1="100" y1="0" x2="100" y2="42" stroke="#475569" />
    <line x1="150" y1="0" x2="150" y2="42" stroke="#475569" />
    <circle cx="25" cy="21" r="4" fill="#818cf8" />
    <text x="75" y="26" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">82</text>
    <circle cx="125" cy="21" r="4" fill="#818cf8" />
    <text x="175" y="26" font-family="monospace" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">91</text>
  </g>

  <!-- Pointers branching to leaves -->
  <g stroke="#818cf8" stroke-width="1.2" fill="none">
    <path d="M 85 252 L 50 330" />
    <path d="M 185 252 L 180 330" />
    <path d="M 325 252 L 310 330" />
    <path d="M 425 252 L 440 330" />
    <path d="M 565 252 L 570 330" />
    <path d="M 665 252 L 700 330" />
  </g>

  <!-- Level 2: Leaf Nodes (Storage Pages) -->
  <g transform="translate(20, 330)">
    <rect width="110" height="38" rx="5" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="55" y="24" font-family="monospace" font-size="12" font-weight="700" fill="#6ee7b7" text-anchor="middle">[1, 4, 8]</text>
  </g>
  <g transform="translate(150, 330)">
    <rect width="110" height="38" rx="5" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="55" y="24" font-family="monospace" font-size="12" font-weight="700" fill="#6ee7b7" text-anchor="middle">[12, 17]</text>
  </g>
  <g transform="translate(280, 330)">
    <rect width="110" height="38" rx="5" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="55" y="24" font-family="monospace" font-size="12" font-weight="700" fill="#6ee7b7" text-anchor="middle">[33, 40]</text>
  </g>
  <g transform="translate(410, 330)">
    <rect width="110" height="38" rx="5" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="55" y="24" font-family="monospace" font-size="12" font-weight="700" fill="#6ee7b7" text-anchor="middle">[48, 52]</text>
  </g>
  <g transform="translate(540, 330)">
    <rect width="110" height="38" rx="5" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="55" y="24" font-family="monospace" font-size="12" font-weight="700" fill="#6ee7b7" text-anchor="middle">[72, 79]</text>
  </g>
  <g transform="translate(670, 330)">
    <rect width="110" height="38" rx="5" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="55" y="24" font-family="monospace" font-size="12" font-weight="700" fill="#6ee7b7" text-anchor="middle">[85, 96]</text>
  </g>

  <!-- Leaf linked list arrows (B+ feature) -->
  <g stroke="#34d399" stroke-width="1.5" fill="none" stroke-dasharray="2,2">
    <line x1="130" y1="349" x2="150" y2="349" />
    <line x1="260" y1="349" x2="280" y2="349" />
    <line x1="390" y1="349" x2="410" y2="349" />
    <line x1="520" y1="349" x2="540" y2="349" />
    <line x1="650" y1="349" x2="670" y2="349" />
  </g>

  <!-- Footer label -->
  <text x="400" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Leaf blocks linked sequentially for high-performance range scanning: [1 .. 96]</text>
</svg>
"""

DIAGRAMS["gradient_descent_optimization.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="gdBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="optTarget" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10b981" />
      <stop offset="100%" stop-color="#059669" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#gdBg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="40" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Gradient Descent Optimization Trajectory on Loss Surface</text>
  <text x="400" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Iterative Update Rule: θ_{t+1} = θ_t - η ∇L(θ_t) Converging to Local/Global Minimum</text>

  <!-- Center Contour Center: (400, 260) -->
  <g transform="translate(400, 260)" fill="none" stroke-width="1.5">
    <!-- Concentric Loss Contours (Ellipses) -->
    <ellipse cx="0" cy="0" rx="340" ry="160" stroke="#1e293b" stroke-width="2" />
    <ellipse cx="0" cy="0" rx="280" ry="130" stroke="#334155" />
    <text x="275" y="5" font-family="monospace" font-size="10" fill="#64748b">L = 12.0</text>

    <ellipse cx="0" cy="0" rx="220" ry="100" stroke="#475569" />
    <text x="215" y="5" font-family="monospace" font-size="10" fill="#64748b">L = 8.0</text>

    <ellipse cx="0" cy="0" rx="160" ry="70" stroke="#3b82f6" opacity="0.6" />
    <text x="155" y="5" font-family="monospace" font-size="10" fill="#60a5fa">L = 4.5</text>

    <ellipse cx="0" cy="0" rx="100" ry="45" stroke="#38bdf8" opacity="0.8" />
    <text x="95" y="5" font-family="monospace" font-size="10" fill="#38bdf8">L = 2.0</text>

    <ellipse cx="0" cy="0" rx="45" ry="20" stroke="#34d399" stroke-width="2" />
    <text x="40" y="5" font-family="monospace" font-size="10" fill="#34d399">L = 0.5</text>

    <!-- Global Minimum Target Point -->
    <circle cx="0" cy="0" r="6" fill="url(#optTarget)" stroke="#a7f3d0" stroke-width="2" />
    <text x="0" y="-12" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#34d399" text-anchor="middle">θ* (Minimum)</text>

    <!-- Axes -->
    <line x1="-350" y1="0" x2="350" y2="0" stroke="#334155" stroke-dasharray="3,3" />
    <line x1="0" y1="-165" x2="0" y2="165" stroke="#334155" stroke-dasharray="3,3" />
    <text x="345" y="-8" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="end">Parameter θ₁</text>
    <text x="8" y="-150" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b">Parameter θ₂</text>

    <!-- Optimization Step Trajectory (Pink/Red to Green) -->
    <!-- Points: θ0(-240, -110) -> θ1(-140, -65) -> θ2(-70, -32) -> θ3(-30, -14) -> θ4(-10, -4) -> θ*(0,0) -->
    <g stroke="#f43f5e" stroke-width="2.5" marker-end="url(#arrow)">
      <line x1="-240" y1="-110" x2="-140" y2="-65" />
      <line x1="-140" y1="-65" x2="-70" y2="-32" />
      <line x1="-70" y1="-32" x2="-30" y2="-14" />
      <line x1="-30" y1="-14" x2="-10" y2="-4" />
      <line x1="-10" y1="-4" x2="-2" y2="-1" />
    </g>

    <!-- Step Points -->
    <circle cx="-240" cy="-110" r="5" fill="#f43f5e" stroke="#fff" stroke-width="1.5" />
    <text x="-240" y="-122" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fb7185" text-anchor="middle">θ₀ (Init)</text>

    <circle cx="-140" cy="-65" r="4" fill="#fb7185" />
    <circle cx="-70" cy="-32" r="4" fill="#fb7185" />
    <circle cx="-30" cy="-14" r="3.5" fill="#fb7185" />
  </g>

  <!-- Legend Box -->
  <g transform="translate(60, 90)">
    <rect width="180" height="74" rx="6" fill="#0f172a" stroke="#475569" />
    <line x1="15" y1="22" x2="35" y2="22" stroke="#f43f5e" stroke-width="2.5" />
    <circle cx="25" cy="22" r="3.5" fill="#f43f5e" />
    <text x="45" y="26" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#e2e8f0">Descent Steps: -η∇L</text>

    <ellipse cx="25" cy="48" rx="10" ry="5" stroke="#38bdf8" fill="none" />
    <text x="45" y="52" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#e2e8f0">Loss Isocontour</text>
  </g>
</svg>
"""

DIAGRAMS["cognitive_load_theory.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="clBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="gradSensory" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0284c7" />
      <stop offset="100%" stop-color="#0369a1" />
    </linearGradient>
    <linearGradient id="gradWorking" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#7c3aed" />
      <stop offset="100%" stop-color="#5b21b6" />
    </linearGradient>
    <linearGradient id="gradLongTerm" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#059669" />
      <stop offset="100%" stop-color="#047857" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#clBg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="40" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Cognitive Load Theory &amp; Human Memory Architecture</text>
  <text x="400" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Sweller (1988): Working Memory Capacity Constraints &amp; Schema Construction</text>

  <!-- 3 Major Stages Containers -->
  <!-- 1. Sensory Memory -->
  <g transform="translate(60, 95)">
    <rect width="180" height="280" rx="8" fill="#131e33" stroke="#0284c7" stroke-width="1.5" />
    <rect x="0" y="0" width="180" height="38" rx="8" fill="url(#gradSensory)" />
    <text x="90" y="24" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">Sensory Memory</text>

    <text x="90" y="70" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Unlimited Capacity</text>
    <text x="90" y="88" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Transient Duration (&lt; 2s)</text>

    <!-- Sensory modalities -->
    <rect x="25" y="120" width="130" height="36" rx="6" fill="#1e293b" stroke="#38bdf8" />
    <text x="90" y="142" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#e0f2fe" text-anchor="middle">Visual Inputs</text>

    <rect x="25" y="170" width="130" height="36" rx="6" fill="#1e293b" stroke="#38bdf8" />
    <text x="90" y="192" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#e0f2fe" text-anchor="middle">Auditory Inputs</text>

    <text x="90" y="250" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="middle">Selective Attention</text>
  </g>

  <!-- Arrow Sensory -> Working -->
  <g stroke="#38bdf8" stroke-width="2" fill="none">
    <path d="M 240 235 L 305 235" />
    <polygon points="305,231 315,235 305,239" fill="#38bdf8" stroke="none" />
  </g>

  <!-- 2. Working Memory (Central Bottleneck) -->
  <g transform="translate(315, 95)">
    <rect width="230" height="280" rx="8" fill="#1e183a" stroke="#7c3aed" stroke-width="2" />
    <rect x="0" y="0" width="230" height="38" rx="8" fill="url(#gradWorking)" />
    <text x="115" y="24" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">Working Memory (Limited)</text>

    <text x="115" y="60" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#c4b5fd" text-anchor="middle">Capacity: 4 ± 1 Elements</text>

    <!-- Three Cognitive Load Components -->
    <rect x="20" y="80" width="190" height="48" rx="6" fill="#831843" stroke="#f43f5e" stroke-width="1.5" />
    <text x="115" y="100" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fecdd3" text-anchor="middle">Intrinsic Load</text>
    <text x="115" y="116" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9.5" fill="#fbcfe8" text-anchor="middle">Material complexity &amp; element interactivity</text>

    <rect x="20" y="138" width="190" height="48" rx="6" fill="#713f12" stroke="#eab308" stroke-width="1.5" />
    <text x="115" y="158" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fef08a" text-anchor="middle">Extraneous Load</text>
    <text x="115" y="174" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9.5" fill="#fef9c3" text-anchor="middle">Poor instructional design / noise (Reduce)</text>

    <rect x="20" y="196" width="190" height="48" rx="6" fill="#064e3b" stroke="#10b981" stroke-width="1.5" />
    <text x="115" y="216" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#a7f3d0" text-anchor="middle">Germane Load</text>
    <text x="115" y="232" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9.5" fill="#d1fae5" text-anchor="middle">Processing effort for schema integration</text>

    <text x="115" y="265" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" font-weight="600" fill="#ec4899" text-anchor="middle">Total Load ≤ Working Memory Limit</text>
  </g>

  <!-- Arrow Working -> Long Term -->
  <g stroke="#10b981" stroke-width="2" fill="none">
    <path d="M 545 235 L 600 235" />
    <polygon points="600,231 610,235 600,239" fill="#10b981" stroke="none" />
  </g>

  <!-- 3. Long-Term Memory -->
  <g transform="translate(610, 95)">
    <rect width="140" height="280" rx="8" fill="#13271f" stroke="#059669" stroke-width="1.5" />
    <rect x="0" y="0" width="140" height="38" rx="8" fill="url(#gradLongTerm)" />
    <text x="70" y="24" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">Long-Term Memory</text>

    <text x="70" y="70" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#a7f3d0" text-anchor="middle">Permanent Storage</text>
    <text x="70" y="88" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#a7f3d0" text-anchor="middle">Unlimited Capacity</text>

    <rect x="15" y="130" width="110" height="40" rx="6" fill="#1e293b" stroke="#34d399" />
    <text x="70" y="154" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#d1fae5" text-anchor="middle">Cognitive Schemas</text>

    <rect x="15" y="185" width="110" height="40" rx="6" fill="#1e293b" stroke="#34d399" />
    <text x="70" y="209" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="600" fill="#d1fae5" text-anchor="middle">Automated Skills</text>
  </g>

  <!-- Footer note -->
  <text x="400" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Effective pedagogy minimizes extraneous load to maximize available capacity for germane schema encoding.</text>
</svg>
"""

DIAGRAMS["peer_review_process.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="prBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="stepSubmit" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0284c7" />
      <stop offset="100%" stop-color="#0369a1" />
    </linearGradient>
    <linearGradient id="stepEditor" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#7c3aed" />
      <stop offset="100%" stop-color="#5b21b6" />
    </linearGradient>
    <linearGradient id="stepReview" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#d97706" />
      <stop offset="100%" stop-color="#b45309" />
    </linearGradient>
    <linearGradient id="stepDecision" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#059669" />
      <stop offset="100%" stop-color="#047857" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#prBg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="40" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Academic Peer Review &amp; Publication Lifecycle</text>
  <text x="400" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Single &amp; Double-Blind Evaluation Workflow for Scholarly Research Validation</text>

  <!-- Step 1: Manuscript Submission -->
  <g transform="translate(50, 110)">
    <rect width="130" height="90" rx="8" fill="#132138" stroke="#38bdf8" stroke-width="1.5" />
    <rect x="0" y="0" width="130" height="26" rx="8" fill="url(#stepSubmit)" />
    <text x="65" y="18" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fff" text-anchor="middle">1. Submission</text>
    <text x="65" y="48" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#e2e8f0" text-anchor="middle">Authors draft &amp;</text>
    <text x="65" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#e2e8f0" text-anchor="middle">submit preprint</text>
    <text x="65" y="80" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9" fill="#94a3b8" text-anchor="middle">Conflict disclosures</text>
  </g>

  <!-- Arrow 1 -> 2 -->
  <line x1="180" y1="155" x2="230" y2="155" stroke="#38bdf8" stroke-width="2" />
  <polygon points="230,151 240,155 230,159" fill="#38bdf8" />

  <!-- Step 2: Editorial Screening -->
  <g transform="translate(240, 110)">
    <rect width="130" height="90" rx="8" fill="#1d1738" stroke="#a78bfa" stroke-width="1.5" />
    <rect x="0" y="0" width="130" height="26" rx="8" fill="url(#stepEditor)" />
    <text x="65" y="18" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fff" text-anchor="middle">2. Editorial Triage</text>
    <text x="65" y="48" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#e2e8f0" text-anchor="middle">Editor-in-Chief</text>
    <text x="65" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#e2e8f0" text-anchor="middle">desk check</text>
    <text x="65" y="80" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9" fill="#f43f5e" text-anchor="middle">Desk Reject risk</text>
  </g>

  <!-- Arrow 2 -> 3 -->
  <line x1="370" y1="155" x2="420" y2="155" stroke="#a78bfa" stroke-width="2" />
  <polygon points="420,151 430,155 420,159" fill="#a78bfa" />

  <!-- Step 3: Peer Review Evaluation -->
  <g transform="translate(430, 110)">
    <rect width="140" height="90" rx="8" fill="#2d1c08" stroke="#f59e0b" stroke-width="1.5" />
    <rect x="0" y="0" width="140" height="26" rx="8" fill="url(#stepReview)" />
    <text x="70" y="18" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fff" text-anchor="middle">3. External Review</text>
    <text x="70" y="48" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#e2e8f0" text-anchor="middle">2–4 Independent</text>
    <text x="70" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#e2e8f0" text-anchor="middle">referee critiques</text>
    <text x="70" y="80" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9" fill="#fbbf24" text-anchor="middle">Methodology &amp; Rigor</text>
  </g>

  <!-- Arrow 3 -> 4 -->
  <line x1="570" y1="155" x2="620" y2="155" stroke="#f59e0b" stroke-width="2" />
  <polygon points="620,151 630,155 620,159" fill="#f59e0b" />

  <!-- Step 4: Editorial Decision -->
  <g transform="translate(630, 110)">
    <rect width="130" height="90" rx="8" fill="#0d281e" stroke="#10b981" stroke-width="1.5" />
    <rect x="0" y="0" width="130" height="26" rx="8" fill="url(#stepDecision)" />
    <text x="65" y="18" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fff" text-anchor="middle">4. Decision</text>
    <text x="65" y="48" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#4ade80" text-anchor="middle">Accept / Publish</text>
    <text x="65" y="64" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#fbbf24" text-anchor="middle">Major Revision</text>
    <text x="65" y="80" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#f87171" text-anchor="middle">Reject</text>
  </g>

  <!-- Revision Loop (Feedback Cycle) -->
  <g transform="translate(180, 260)">
    <rect width="440" height="85" rx="8" fill="#1e293b" stroke="#eab308" stroke-dasharray="4,4" stroke-width="1.5" />
    <text x="220" y="28" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="700" fill="#fef08a" text-anchor="middle">Revision &amp; Response Loop (Major / Minor Revision)</text>
    <text x="220" y="50" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10.5" fill="#cbd5e1" text-anchor="middle">Authors address referee points point-by-point with new experiments &amp; manuscript diffs.</text>
    <text x="220" y="68" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" fill="#94a3b8" text-anchor="middle">Re-evaluated by original reviewers or editor before final publication.</text>
  </g>

  <!-- Flow connecting decision back to revision, and revision back to submission/editor -->
  <g stroke="#eab308" stroke-width="1.5" fill="none">
    <path d="M 695 200 L 695 300 L 620 300" />
    <polygon points="620,296 610,300 620,304" fill="#eab308" stroke="none" />

    <path d="M 180 300 L 115 300 L 115 205" />
    <polygon points="111,205 115,195 119,205" fill="#eab308" stroke="none" />
  </g>

  <text x="400" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Peer review ensures methodological integrity, reproducibility, and ethical compliance across science.</text>
</svg>
"""

DIAGRAMS["public_key_cryptography.svg"] = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
  <defs>
    <linearGradient id="pkBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
    <linearGradient id="gradAlice" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="100%" stop-color="#0284c7" />
    </linearGradient>
    <linearGradient id="gradBob" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#10b981" />
      <stop offset="100%" stop-color="#047857" />
    </linearGradient>
    <linearGradient id="gradKeyPublic" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f59e0b" />
      <stop offset="100%" stop-color="#d97706" />
    </linearGradient>
    <linearGradient id="gradKeyPrivate" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ec4899" />
      <stop offset="100%" stop-color="#be185d" />
    </linearGradient>
  </defs>

  <rect width="800" height="450" rx="12" fill="url(#pkBg)" />
  <rect x="1" y="1" width="798" height="448" rx="11" fill="none" stroke="#334155" stroke-width="1.5" />

  <!-- Header -->
  <text x="400" y="40" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc" text-anchor="middle">Asymmetric Public-Key Cryptography Architecture</text>
  <text x="400" y="62" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" fill="#94a3b8" text-anchor="middle">Diffie-Hellman / RSA Model: Public Encryption Key &amp; Mathematically Linked Private Decryption Key</text>

  <!-- Sender (Alice) Box -->
  <g transform="translate(60, 100)">
    <rect width="180" height="260" rx="8" fill="#132138" stroke="#0284c7" stroke-width="1.5" />
    <rect x="0" y="0" width="180" height="34" rx="8" fill="url(#gradAlice)" />
    <text x="90" y="22" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">Sender (Alice)</text>

    <!-- Plaintext -->
    <rect x="25" y="55" width="130" height="40" rx="6" fill="#1e293b" stroke="#38bdf8" />
    <text x="90" y="79" font-family="monospace" font-size="12" font-weight="700" fill="#e0f2fe" text-anchor="middle">Plaintext m</text>

    <!-- Encryption Box -->
    <rect x="25" y="140" width="130" height="60" rx="6" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5" />
    <text x="90" y="162" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#fbbf24" text-anchor="middle">Encrypt: c = E(m, K_pub)</text>
    <text x="90" y="185" font-family="monospace" font-size="10" fill="#94a3b8" text-anchor="middle">c = mᵉ mod N</text>

    <path d="M 90 95 L 90 140" stroke="#38bdf8" stroke-width="1.5" />
  </g>

  <!-- Insecure Channel (Center) -->
  <g transform="translate(290, 150)">
    <rect width="220" height="150" rx="8" fill="#1e1b2e" stroke="#ef4444" stroke-dasharray="4,4" stroke-width="1.5" />
    <text x="110" y="28" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#f87171" text-anchor="middle">Insecure Public Channel</text>

    <!-- Ciphertext payload -->
    <rect x="30" y="50" width="160" height="42" rx="6" fill="#0f172a" stroke="#ef4444" stroke-width="1.5" />
    <text x="110" y="72" font-family="monospace" font-size="11" font-weight="700" fill="#fca5a5" text-anchor="middle">Ciphertext c (Encrypted)</text>
    <text x="110" y="85" font-family="monospace" font-size="9" fill="#94a3b8" text-anchor="middle">7f9a2b8c4d1e0f...</text>

    <text x="110" y="125" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9.5" fill="#fca5a5" text-anchor="middle">Eavesdropper cannot invert c</text>
    <text x="110" y="139" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="9.5" fill="#fca5a5" text-anchor="middle">without Private Key d</text>
  </g>

  <!-- Channel Flow Arrows -->
  <g stroke="#f59e0b" stroke-width="2" fill="none">
    <path d="M 215 230 L 290 230" />
    <polygon points="290,226 300,230 290,234" fill="#f59e0b" stroke="none" />
  </g>
  <g stroke="#ef4444" stroke-width="2" fill="none">
    <path d="M 510 230 L 560 230" />
    <polygon points="560,226 570,230 560,234" fill="#ef4444" stroke="none" />
  </g>

  <!-- Recipient (Bob) Box -->
  <g transform="translate(560, 100)">
    <rect width="180" height="260" rx="8" fill="#13271f" stroke="#059669" stroke-width="1.5" />
    <rect x="0" y="0" width="180" height="34" rx="8" fill="url(#gradBob)" />
    <text x="90" y="22" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">Recipient (Bob)</text>

    <!-- Decryption Box -->
    <rect x="25" y="100" width="130" height="60" rx="6" fill="#1e293b" stroke="#ec4899" stroke-width="1.5" />
    <text x="90" y="122" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#f472b6" text-anchor="middle">Decrypt: m = D(c, K_priv)</text>
    <text x="90" y="145" font-family="monospace" font-size="10" fill="#94a3b8" text-anchor="middle">m = cᵈ mod N</text>

    <!-- Recovered Plaintext -->
    <rect x="25" y="195" width="130" height="40" rx="6" fill="#1e293b" stroke="#10b981" />
    <text x="90" y="219" font-family="monospace" font-size="12" font-weight="700" fill="#a7f3d0" text-anchor="middle">Plaintext m</text>

    <path d="M 90 160 L 90 195" stroke="#10b981" stroke-width="1.5" />
  </g>

  <!-- Key Pair Distribution -->
  <!-- Bob's Public Key sent to Alice -->
  <path d="M 650 95 L 650 78 L 150 78 L 150 135" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="3,3" fill="none" />
  <rect x="340" y="68" width="120" height="22" rx="4" fill="#78350f" stroke="#f59e0b" />
  <text x="400" y="83" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" font-weight="700" fill="#fef08a" text-anchor="middle">Bob's Public Key (e, N)</text>

  <!-- Footer -->
  <text x="400" y="415" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#94a3b8" text-anchor="middle">Underpinned by computational intractability of prime factorization and discrete logarithms.</text>
</svg>
"""

def generate():
    for filename, content in DIAGRAMS.items():
        filepath = OUT_DIR / filename
        filepath.write_text(content.strip(), encoding="utf-8")
        print(f"Generated {filepath.name} ({len(content)} bytes)")
    print(f"All {len(DIAGRAMS)} diagrams successfully created in {OUT_DIR}.")

if __name__ == "__main__":
    generate()
