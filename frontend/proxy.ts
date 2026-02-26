import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { resolveSessionFromRequest, rotateSessionFromRefresh, type ServerRole } from "@/lib/security/role_cookie";

function roleHome(role: ServerRole): string {
  if (role === "admin") return "/admin";
  if (role === "clinician") return "/doctor";
  return "/patient";
}

function requiredRole(pathname: string): ServerRole | null {
  if (pathname.startsWith("/admin")) return "admin";
  if (pathname.startsWith("/doctor")) return "clinician";
  if (pathname.startsWith("/patient")) return "patient";
  return null;
}

function buildAuthRedirect(request: NextRequest, errorCode: string): NextResponse {
  const url = request.nextUrl.clone();
  const nextPath = `${request.nextUrl.pathname}${request.nextUrl.search || ""}`;
  url.pathname = "/";
  url.searchParams.set("next", nextPath);
  url.searchParams.set("error", errorCode);
  return NextResponse.redirect(url);
}

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const required = requiredRole(pathname);
  if (!required) return NextResponse.next();

  const session = await resolveSessionFromRequest(request);
  if (!session) {
    return buildAuthRedirect(request, "auth_required");
  }

  if (session.role !== required) {
    const url = request.nextUrl.clone();
    url.pathname = roleHome(session.role);
    url.searchParams.set("error", "role_access_denied");
    return NextResponse.redirect(url);
  }

  const response = NextResponse.next();
  if (session.source === "refresh") {
    await rotateSessionFromRefresh(response, session, { path: request.nextUrl.pathname });
  }
  return response;
}

export const config = {
  matcher: ["/doctor/:path*", "/patient/:path*", "/admin/:path*"]
};
