// src/components/Chip.tsx
// Rôle: badge visuel (rubrique/menu) utilisé dans le header et les cartes.

export default function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center px-3 py-1 rounded-full bg-black text-white text-xs tracking-widest">
      {children}
    </span>
  );
}