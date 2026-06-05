"use client";
import { useEffect, useRef, ReactNode } from "react";

interface Props {
  children: ReactNode;
  delay?: number;
  className?: string;
  direction?: "up" | "left" | "right";
}

export function ScrollReveal({ children, delay = 0, className = "", direction = "up" }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let revealed = false;
    const reveal = () => {
      if (revealed) return;
      revealed = true;
      setTimeout(() => el.classList.add("is-visible"), delay);
    };

    // Check after a small delay so anchor scroll + hydration have settled
    const timer = setTimeout(() => {
      const rect = el.getBoundingClientRect();
      if (rect.top < window.innerHeight && rect.bottom > 0) {
        reveal();
        return;
      }
      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            reveal();
            observer.unobserve(el);
          }
        },
        { threshold: 0.05, rootMargin: "0px 0px -20px 0px" }
      );
      observer.observe(el);
      return () => observer.disconnect();
    }, 80);

    return () => clearTimeout(timer);
  }, [delay]);

  const dirClass = direction === "left" ? "reveal-left" : direction === "right" ? "reveal-right" : "reveal-up";
  return (
    <div ref={ref} className={`${dirClass} ${className}`}>
      {children}
    </div>
  );
}
