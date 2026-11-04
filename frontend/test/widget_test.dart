import 'package:flutter_test/flutter_test.dart';
import 'package:purchase_intelligence/main.dart';

void main() {
  testWidgets('PIA app builds and shows the Scan tab', (tester) async {
    await tester.pumpWidget(const PiaApp());
    expect(find.textContaining('Purchase Intelligence'), findsWidgets);
    expect(find.text('Scan'), findsOneWidget);
    expect(find.text('Capture'), findsOneWidget);
  });
}
