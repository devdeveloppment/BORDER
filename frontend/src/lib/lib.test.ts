import { describe, expect, it } from "vitest";
import { ageLabel, formatNumber, formatPercent, variation } from "./format";
import { levelFromScore } from "./labels";
import { MOCK_ROLE_PERMISSIONS as DEFAULT_ROLE_PERMISSIONS, mockPermissionsForRoles as permissionsForRoles } from "@/mocks/roles";
import { PERMISSIONS } from "./permissions";

describe("formatage français (§11.4)", () => {
  it("utilise l'espace simple comme séparateur de milliers", () => {
    expect(formatNumber(12480)).toBe("12 480");
    expect(formatNumber(1234567)).toBe("1 234 567");
  });

  it("formate les pourcentages avec signe et virgule", () => {
    expect(formatPercent(38)).toBe("+38 %");
    expect(formatPercent(-4.24)).toBe("-4,2 %");
    expect(formatPercent(12.36)).toBe("+12,4 %");
    expect(formatPercent(0)).toBe("0 %");
  });

  it("calcule une variation relative sans division par zéro", () => {
    expect(variation(138, 100)).toBeCloseTo(38);
    expect(variation(0, 0)).toBe(0);
    expect(variation(5, 0)).toBe(100);
  });

  it("exprime une ancienneté lisible", () => {
    const now = new Date("2026-10-08T12:00:00Z");
    expect(ageLabel("2026-10-08T11:30:00Z", now)).toBe("30 min");
    expect(ageLabel("2026-10-08T02:00:00Z", now)).toBe("10 h");
    expect(ageLabel("2026-10-04T12:00:00Z", now)).toBe("4 j");
  });
});

describe("niveaux d'indicateur (§9.7)", () => {
  it.each([
    [0, "NORMAL"],
    [39, "NORMAL"],
    [40, "ATTENTION"],
    [69, "ATTENTION"],
    [70, "ELEVE"],
    [89, "ELEVE"],
    [90, "CRITIQUE"],
    [100, "CRITIQUE"],
  ])("score %i → %s", (score, level) => {
    expect(levelFromScore(score)).toBe(level);
  });
});

// Matrice des MOCKS (maquette) : reproduit le catalogue du backend, qui reste la seule autorité (P2.10).
describe("matrice des rôles simulée (§7.3, décisions P9/P10)", () => {
  it("n'accorde aucune donnée opérationnelle au Super Admin", () => {
    const perms = DEFAULT_ROLE_PERMISSIONS.SUPER_ADMIN;
    expect(perms).not.toContain(PERMISSIONS.dashboardView);
    expect(perms).not.toContain(PERMISSIONS.activitiesView);
    expect(perms).not.toContain(PERMISSIONS.alertsView);
  });

  it("interdit l'import à l'Agent par défaut", () => {
    expect(DEFAULT_ROLE_PERMISSIONS.AGENT).not.toContain(PERMISSIONS.importsRun);
  });

  it("réserve la décision sur les alertes au Superviseur et à l'Admin", () => {
    const deciders = Object.entries(DEFAULT_ROLE_PERMISSIONS).filter(([, p]) => (p as string[]).includes(PERMISSIONS.alertsDecide)).map(([r]) => r);
    expect(deciders.sort()).toEqual(["ORG_ADMIN", "SUPERVISOR"]);
  });

  it("ne donne à l'Auditeur aucune permission d'écriture", () => {
    const writes = [PERMISSIONS.activitiesCreate, PERMISSIONS.alertsTake, PERMISSIONS.alertsComment, PERMISSIONS.alertsDecide, PERMISSIONS.settingsManage, PERMISSIONS.usersManage, PERMISSIONS.reportsGenerate, PERMISSIONS.importsRun];
    for (const w of writes) expect(DEFAULT_ROLE_PERMISSIONS.AUDITOR).not.toContain(w);
  });

  it("fusionne les permissions de plusieurs rôles sans doublon", () => {
    const merged = permissionsForRoles(["ANALYST", "AUDITOR"]);
    expect(new Set(merged).size).toBe(merged.length);
    expect(merged).toContain(PERMISSIONS.auditView);
    expect(merged).toContain(PERMISSIONS.whatIfRun);
  });
});
