import { createContext, useContext, useState, type ReactNode } from "react";
import type { PeriodKey } from "@/lib/api/types";

interface PeriodValue {
  period: PeriodKey;
  setPeriod: (period: PeriodKey) => void;
}

const PeriodContext = createContext<PeriodValue | null>(null);

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [period, setPeriod] = useState<PeriodKey>("7d");
  return <PeriodContext.Provider value={{ period, setPeriod }}>{children}</PeriodContext.Provider>;
}

export function usePeriod(): PeriodValue {
  const ctx = useContext(PeriodContext);
  if (!ctx) throw new Error("usePeriod doit être utilisé dans <PeriodProvider>");
  return ctx;
}
