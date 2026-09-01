export function mergeTripPilotEnv(
  repositoryEnv: Record<string, string>,
  webEnv: Record<string, string>,
) {
  return { ...repositoryEnv, ...webEnv }
}
