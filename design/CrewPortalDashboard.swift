import SwiftUI

struct CrewPortalDashboardView: View {
    @State private var expandedDuty = true
    @State private var expandedStats = false
    @State private var expandedLayovers = false
    @State private var expandedTimeOff = false
    @State private var expandedFinance = false
    @State private var expandedReports = false

    var body: some View {
        ZStack(alignment: .bottom) {
            Theme.background.ignoresSafeArea()

            VStack(spacing: 0) {
                header
                ScrollView {
                    VStack(spacing: 16) {
                        welcome
                        disclosureCard(
                            icon: "airplane.departure",
                            iconColor: Theme.primary,
                            title: "Upcoming Duty",
                            subtitle: "LA3445 (GRU → FOR)",
                            isExpanded: $expandedDuty
                        ) { upcomingDutyContent }

                        disclosureCard(
                            icon: "chart.bar.fill",
                            iconColor: .green,
                            title: "Flight Statistics",
                            subtitle: "85h 30m Total Time",
                            isExpanded: $expandedStats
                        ) { flightStatsContent }

                        disclosureCard(
                            icon: "bed.double.fill",
                            iconColor: .blue,
                            title: "Layovers",
                            subtitle: "3 Destinations Upcoming",
                            isExpanded: $expandedLayovers
                        ) { layoversContent }

                        disclosureCard(
                            icon: "calendar",
                            iconColor: .purple,
                            title: "Time Off",
                            subtitle: "10 Total Days Off",
                            isExpanded: $expandedTimeOff
                        ) { timeOffContent }

                        disclosureCard(
                            icon: "dollarsign.circle.fill",
                            iconColor: .orange,
                            title: "Finance",
                            subtitle: "$4,250 Earnings",
                            isExpanded: $expandedFinance
                        ) { financeContent }

                        disclosureCard(
                            icon: "doc.text.fill",
                            iconColor: .gray,
                            title: "Reports & Tools",
                            subtitle: "Monthly Roster, Tax, Bidding",
                            isExpanded: $expandedReports
                        ) { reportsContent }

                        Spacer(minLength: 96)
                    }
                    .padding(16)
                }
            }

            bottomBar
        }
    }
}

private extension CrewPortalDashboardView {
    var header: some View {
        HStack {
            HStack(spacing: 12) {
                AsyncImage(url: URL(string: "https://lh3.googleusercontent.com/aida-public/AB6AXuCyUEqgttnz13k2qrAHAclpyFYFgPYh1rUv0_2PkdWtMwJUyKGGf5CXjMrAPeszqEJMC8Wy_cI3lJF4w0dxXfe4r4-bGz1CMmt4qeXEaDs9FOJCgcMtKpoy-DikvmOLVAzhUlEY7uILNAwcBqH_-0s3FzSOAFOivZznICfjwDfAQPoFY4_Y5JsUQNSsWUGXdNewZRnmRAMPAJYaJxTJC9TWd19XBQdWXKrJGwRbkfUQRcTLbCQdW1OaUnW3gWNBzxMy8vhy3g5Xsi0")) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    Circle().fill(Color.gray.opacity(0.25))
                }
                .frame(width: 40, height: 40)
                .clipShape(Circle())
                .overlay(Circle().stroke(Theme.primary, lineWidth: 2))

                Text("Crew Portal")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Theme.textPrimary)
            }

            Spacer()

            HStack(spacing: 12) {
                Image(systemName: "bell")
                    .foregroundStyle(Theme.textSecondary)
                Image(systemName: "line.3.horizontal")
                    .foregroundStyle(Theme.textPrimary)
            }
            .font(.system(size: 18, weight: .semibold))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Theme.surface)
        .overlay(alignment: .bottom) { Divider().overlay(Theme.border) }
    }

    var welcome: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Welcome back, Sarah")
                .font(.system(size: 30, weight: .black))
                .foregroundStyle(Theme.textPrimary)
            HStack(spacing: 8) {
                Circle()
                    .fill(.green)
                    .frame(width: 8, height: 8)
                Text("Status: Active")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.textSecondary)
                Text("•")
                    .foregroundStyle(Theme.textSecondary)
                Text("Next Duty in 14h 30m")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.textSecondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.bottom, 4)
    }

    func disclosureCard<Content: View>(
        icon: String,
        iconColor: Color,
        title: String,
        subtitle: String,
        isExpanded: Binding<Bool>,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { isExpanded.wrappedValue.toggle() }
            } label: {
                HStack {
                    HStack(spacing: 12) {
                        RoundedRectangle(cornerRadius: 8)
                            .fill(iconColor.opacity(0.15))
                            .frame(width: 36, height: 36)
                            .overlay {
                                Image(systemName: icon)
                                    .font(.system(size: 18, weight: .bold))
                                    .foregroundStyle(iconColor)
                            }
                        VStack(alignment: .leading, spacing: 2) {
                            Text(title.uppercased())
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(Theme.textSecondary)
                            Text(subtitle)
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Theme.textPrimary)
                        }
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.system(size: 12, weight: .bold))
                        .rotationEffect(.degrees(isExpanded.wrappedValue ? 180 : 0))
                        .foregroundStyle(Theme.textSecondary)
                }
                .padding(16)
            }
            .buttonStyle(.plain)

            if isExpanded.wrappedValue {
                Divider().overlay(Theme.border.opacity(0.6))
                content().padding(16)
            }
        }
        .background(Theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.border, lineWidth: 1))
    }

    var upcomingDutyContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Airbus A320 NEO • Gate 212")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Theme.textSecondary)

            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("DEPARTS (ZULU)")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Theme.textSecondary)
                    Text("10:00 Z")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Theme.textPrimary)
                }
                Spacer()
                VStack(alignment: .leading, spacing: 2) {
                    Text("DURATION")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Theme.textSecondary)
                    Text("7h 45m")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Theme.textPrimary)
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("CREW")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.textSecondary)
                HStack(spacing: -8) {
                    ForEach(0..<3, id: \.self) { _ in
                        Circle()
                            .fill(Color.gray.opacity(0.25))
                            .frame(width: 32, height: 32)
                            .overlay(Circle().stroke(Theme.surface, lineWidth: 2))
                    }
                    Circle()
                        .fill(Theme.surfaceHighlight)
                        .frame(width: 32, height: 32)
                        .overlay(Text("+5").font(.system(size: 11, weight: .bold)).foregroundStyle(Theme.textSecondary))
                }
            }

            Button(action: {}) {
                HStack {
                    Text("View Briefing")
                    Image(systemName: "arrow.right")
                }
                .font(.system(size: 14, weight: .bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 11)
                .background(Theme.primary)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            Button(action: {}) {
                HStack {
                    Image(systemName: "cloud")
                    Text("Weather")
                }
                .font(.system(size: 14, weight: .bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 11)
                .background(Theme.surfaceHighlight)
                .foregroundStyle(Theme.textPrimary)
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    var flightStatsContent: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                statChip(title: "Total Flights", value: "14 +2")
                statChip(title: "Overnighters", value: "6")
            }
            statChip(title: "Total Duty Time", value: "112h 15m")

            progressRow(title: "Short Layovers (<14h)", value: "2", progress: 0.25, color: .orange)
            progressRow(title: "Ground Duties", value: "1", progress: 0.15, color: .blue)
        }
    }

    var layoversContent: some View {
        VStack(spacing: 10) {
            layoverItem(code: "BSB", city: "Brasília, Brasil", note: "Oct 12 • Hotel S4", rest: "48h Rest", color: .green)
            layoverItem(code: "FOR", city: "Fortaleza, Ceará", note: "Oct 18 • IBIS Fortaleza", rest: "72h Rest", color: .blue)
            layoverItem(code: "MAO", city: "Eduardo Gomes, Manaus", note: "Oct 25 • Holiday INN Manaus", rest: "24h Rest", color: .gray)

            Button("View Full Schedule") {}
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Theme.primary)
                .frame(maxWidth: .infinity)
                .padding(.top, 4)
        }
    }

    var timeOffContent: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                statCard(title: "TOTAL OFF", value: "10", valueColor: Theme.textPrimary)
                statCard(title: "GRANTED", value: "4/4", valueColor: .green)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("\"OFF\" DAYS CALENDAR")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.textSecondary)
                let days = ["02", "03", "09", "15", "16", "+5"]
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 6), spacing: 8) {
                    ForEach(days, id: \.self) { day in
                        Text(day)
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(day == "+5" ? Theme.textSecondary.opacity(0.7) : Theme.textSecondary)
                            .frame(height: 32)
                            .frame(maxWidth: .infinity)
                            .background(Theme.surfaceHighlight)
                            .overlay(
                                RoundedRectangle(cornerRadius: 6)
                                    .stroke(day == "+5" ? Theme.border : .clear, style: StrokeStyle(lineWidth: 1, dash: [3]))
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                }
            }
        }
    }

    var financeContent: some View {
        VStack(spacing: 12) {
            HStack {
                Text("Pending Per Diems")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.textSecondary)
                Spacer()
                HStack(spacing: 4) {
                    Text("$120.00")
                        .font(.system(size: 14, weight: .bold))
                    Image(systemName: "clock.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(.yellow)
                }
            }
            .padding(12)
            .background(Theme.surfaceHighlight)
            .clipShape(RoundedRectangle(cornerRadius: 10))

            Button("Submit Expenses") {}
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Theme.textPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border, lineWidth: 1))
        }
    }

    var reportsContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("QUICK GENERATION")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(Theme.textSecondary)
            toolButton("Monthly Roster")
            toolButton("Tax Report")

            VStack(alignment: .leading, spacing: 6) {
                Text("BIDDING STATUS")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.textSecondary)
                HStack(spacing: 6) {
                    Circle().fill(.green).frame(width: 8, height: 8)
                    Text("Open")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(.green)
                }
                Text("Bid period closes in 2 days. Check your requests.")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.textSecondary)
            }
        }
    }

    var bottomBar: some View {
        HStack {
            navItem("square.grid.2x2.fill", "Portal", selected: true)
            navItem("calendar", "Calendário")

            Button(action: {}) {
                Image(systemName: "plus")
                    .font(.system(size: 22, weight: .bold))
                    .frame(width: 52, height: 52)
                    .background(Theme.primary)
                    .foregroundStyle(.white)
                    .clipShape(Circle())
            }
            .offset(y: -18)

            VStack(spacing: 3) {
                ZStack(alignment: .topTrailing) {
                    Image(systemName: "envelope")
                    Text("3")
                        .font(.system(size: 8, weight: .bold))
                        .frame(width: 14, height: 14)
                        .background(Color.red)
                        .foregroundStyle(.white)
                        .clipShape(Circle())
                        .offset(x: 8, y: -6)
                }
                Text("Alertas").font(.system(size: 10, weight: .bold))
            }
            .foregroundStyle(Theme.textSecondary)
            .frame(maxWidth: .infinity)

            navItem("gearshape", "Config")
        }
        .padding(.top, 8)
        .padding(.horizontal, 16)
        .padding(.bottom, 12)
        .background(Theme.surface)
        .overlay(alignment: .top) { Divider().overlay(Theme.border) }
    }
}

private extension CrewPortalDashboardView {
    func navItem(_ icon: String, _ title: String, selected: Bool = false) -> some View {
        VStack(spacing: 3) {
            Image(systemName: icon)
            Text(title).font(.system(size: 10, weight: .bold))
        }
        .foregroundStyle(selected ? Theme.primary : Theme.textSecondary)
        .frame(maxWidth: .infinity)
    }

    func statChip(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(Theme.textSecondary)
            Text(value)
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Theme.textPrimary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Theme.surfaceHighlight)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    func statCard(title: String, value: String, valueColor: Color) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.system(size: 24, weight: .bold))
                .foregroundStyle(valueColor)
            Text(title)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(Theme.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(12)
        .background(Theme.surfaceHighlight)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    func progressRow(title: String, value: String, progress: CGFloat, color: Color) -> some View {
        VStack(spacing: 4) {
            HStack {
                Text(title).font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.textSecondary)
                Spacer()
                Text(value).font(.system(size: 14, weight: .bold)).foregroundStyle(Theme.textPrimary)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.surfaceHighlight)
                    Capsule().fill(color).frame(width: geo.size.width * progress)
                }
            }
            .frame(height: 6)
        }
    }

    func layoverItem(code: String, city: String, note: String, rest: String, color: Color) -> some View {
        HStack(spacing: 10) {
            Circle()
                .fill(Theme.background)
                .frame(width: 32, height: 32)
                .overlay(Text(code).font(.system(size: 10, weight: .black)).foregroundStyle(Theme.textSecondary))
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(city).font(.system(size: 12, weight: .bold)).foregroundStyle(Theme.textPrimary)
                    Spacer()
                    Text(rest)
                        .font(.system(size: 9, weight: .bold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(color.opacity(0.15))
                        .foregroundStyle(color)
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                }
                Text(note).font(.system(size: 10)).foregroundStyle(Theme.textSecondary)
            }
        }
        .padding(10)
        .background(Theme.surfaceHighlight)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    func toolButton(_ title: String) -> some View {
        Button(action: {}) {
            HStack {
                Text(title).font(.system(size: 12, weight: .medium))
                Spacer()
                Image(systemName: "arrow.down.circle")
                    .foregroundStyle(Theme.textSecondary)
            }
            .padding(12)
            .background(Theme.surfaceHighlight)
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
    }
}

private enum Theme {
    static let primary = Color(red: 19 / 255, green: 109 / 255, blue: 236 / 255)
    static let background = Color(red: 16 / 255, green: 24 / 255, blue: 34 / 255)
    static let surface = Color(red: 25 / 255, green: 36 / 255, blue: 51 / 255)
    static let surfaceHighlight = Color(red: 35 / 255, green: 51 / 255, blue: 72 / 255)
    static let border = Color(red: 45 / 255, green: 60 / 255, blue: 80 / 255)
    static let textPrimary = Color.white
    static let textSecondary = Color(red: 146 / 255, green: 169 / 255, blue: 201 / 255)
}

#Preview {
    CrewPortalDashboardView()
        .preferredColorScheme(.dark)
}
