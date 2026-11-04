import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'api.dart';

/// Purchase Intelligence by TAIG ITS — Flutter UI, single user, no AI.
/// 4 screens, in order: Snap, Review & Confirm, Pantry, Analytics.
/// Backend: Droplet PIA API (see api.dart). Certs null for the demo.
void main() => runApp(const PiaApp());

class PiaApp extends StatelessWidget {
  const PiaApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Purchase Intelligence',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF7A9A7E)),
        scaffoldBackgroundColor: const Color(0xFFDBD5C9),
        cardColor: const Color(0xFFF5F0E6),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final api = PiaApi();
  int _tab = 0;
  Map<String, dynamic>? _extraction;

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      ScanScreen(api: api, onExtracted: (e) => setState(() {
            _extraction = e;
            _tab = 1;
          })),
      ReviewScreen(api: api, extraction: _extraction),
      PantryScreen(api: api),
      AnalyticsScreen(api: api),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Purchase Intelligence\nby TAIG ITS')),
      body: pages[_tab],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.camera_alt), label: 'Scan'),
          NavigationDestination(icon: Icon(Icons.checklist), label: 'Review'),
          NavigationDestination(icon: Icon(Icons.kitchen), label: 'Pantry'),
          NavigationDestination(icon: Icon(Icons.bar_chart), label: 'Analytics'),
        ],
      ),
    );
  }
}

class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key, required this.api, required this.onExtracted});
  final PiaApi api;
  final void Function(Map<String, dynamic>) onExtracted;
  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  String _msg = 'Snap a receipt. Nothing counts until you confirm it.';
  bool _busy = false;

  Future<void> _snap() async {
    setState(() { _busy = true; _msg = 'Uploading…'; });
    try {
      final picked = await ImagePicker().pickImage(source: ImageSource.camera);
      final file = picked ?? await ImagePicker().pickImage(source: ImageSource.gallery);
      if (file == null) { setState(() { _msg = 'No receipt picked.'; _busy = false; }); return; }
      final bytes = await file.readAsBytes();
      final intake = await widget.api.uploadReceipt(bytes, file.name);
      setState(() => _msg = 'Receipt preserved. Reading it…');
      final extraction = await widget.api.extract(intake['evidence_id'] as String);
      widget.onExtracted(extraction);
    } catch (e) {
      setState(() => _msg = 'Could not read that receipt: $e');
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          const Text('Snap a receipt', style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(_msg, textAlign: TextAlign.center),
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: _busy ? null : _snap,
            icon: const Icon(Icons.camera_alt),
            label: const Text('Capture'),
          ),
        ]),
      ),
    );
  }
}

class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key, required this.api, required this.extraction});
  final PiaApi api;
  final Map<String, dynamic>? extraction;
  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  String _msg = '';
  final Map<String, TextEditingController> _edits = {};

  @override
  void dispose() {
    for (final c in _edits.values) { c.dispose(); }
    super.dispose();
  }

  Future<void> _confirm() async {
    final ext = widget.extraction;
    if (ext == null) return;
    setState(() => _msg = 'Confirming…');
    try {
      final lines = (ext['lines'] as List<dynamic>);
      final payload = {
        'evidence_id': ext['evidence_id'],
        'extraction_id': ext['extraction_id'],
        'merchant': ext['merchant_normalized_candidate'],
        'purchase_date': ext['purchase_date_candidate'],
        'purchase_time': ext['purchase_time_candidate'],
        'subtotal': ext['subtotal_candidate'],
        'tax': ext['tax_candidate'],
        'total': ext['total_candidate'],
        'items': lines.map((l) {
          final edited = _edits[l['line_id'] as String]?.text;
          return {
            'source_line_id': l['line_id'],
            'item_name': (edited != null && edited.isNotEmpty) ? edited : l['normalized_name_candidate'],
            'quantity': l['quantity_candidate'],
            'unit_price': l['unit_price_candidate'],
            'line_total': l['line_total_candidate'],
          };
        }).toList(),
      };
      final result = await widget.api.confirm(payload);
      setState(() => _msg = 'Confirmed. Purchase ${result['purchase_id']}. Pantry updated.');
    } catch (e) {
      setState(() => _msg = 'Confirm failed: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final ext = widget.extraction;
    if (ext == null) {
      return const Center(child: Text('No receipt yet. Snap one on the Scan tab.'));
    }
    final lines = (ext['lines'] as List<dynamic>);
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Review & Confirm — ${ext['merchant_normalized_candidate'] ?? ''}',
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      const Text('Original receipt is kept separate. Nothing counts until you confirm.'),
      if (ext['suggestions'] != null && (ext['suggestions'] as Map).isNotEmpty)
        const Card(child: ListTile(title: Text('Suggestions from your corrections are flagged, never auto-applied.'))),
      ...lines.map((l) {
        final ctrl = _edits.putIfAbsent(
            l['line_id'] as String, () => TextEditingController(text: l['normalized_name_candidate'] ?? ''));
        return Card(
          child: ListTile(
            title: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'Item name')),
            subtitle: Text('${l['raw_text'] ?? ''}'),
            trailing: Text('${l['line_total_candidate'] ?? ''}'),
          ),
        );
      }),
      const SizedBox(height: 12),
      ElevatedButton(onPressed: _confirm, child: const Text('Confirm purchase')),
      if (_msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_msg)),
    ]);
  }
}

class PantryScreen extends StatefulWidget {
  const PantryScreen({super.key, required this.api});
  final PiaApi api;
  @override
  State<PantryScreen> createState() => _PantryScreenState();
}

class _PantryScreenState extends State<PantryScreen> {
  List<dynamic> _items = [];
  String _msg = '';

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try { final items = await widget.api.pantry(); setState(() => _items = items); } catch (e) { setState(() => _msg = '$e'); }
  }

  Future<void> _set(String id, String status) async {
    await widget.api.pantryStatus(id, status);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('What is in the house', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
      const Text('Tap an item to mark it In stock, Used, or Gone.'),
      ..._items.map((item) => Card(
            child: ListTile(
              title: Text('${item['item_name']}'),
              subtitle: Text('${item['status']} • qty ${item['qty_on_hand']}${item['low'] == true ? ' • Low' : ''}'),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                TextButton(onPressed: () => _set(item['pantry_item_id'] as String, 'in_stock'), child: const Text('In stock')),
                TextButton(onPressed: () => _set(item['pantry_item_id'] as String, 'used'), child: const Text('Used')),
                TextButton(onPressed: () => _set(item['pantry_item_id'] as String, 'gone'), child: const Text('Gone')),
              ]),
            ),
          )),
      const SizedBox(height: 12),
      ElevatedButton.icon(
        onPressed: () async {
          final name = TextEditingController();
          final qty = TextEditingController(text: '1');
          final ok = await showDialog<bool>(
            context: context,
            builder: (c) => AlertDialog(
              title: const Text('Add item'),
              content: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(controller: name, decoration: const InputDecoration(labelText: 'Item name')),
                TextField(controller: qty, decoration: const InputDecoration(labelText: 'Quantity')),
              ]),
              actions: [
                TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
                TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Add')),
              ],
            ),
          );
          if (ok == true && name.text.isNotEmpty) {
            await widget.api.addPantryItem(name.text, qty.text);
            await _load();
          }
        },
        icon: const Icon(Icons.add),
        label: const Text('Add item'),
      ),
      if (_msg.isNotEmpty) Text(_msg),
    ]);
  }
}

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key, required this.api});
  final PiaApi api;
  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  Map<String, dynamic>? _weekly;
  Map<String, dynamic>? _most;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try {
      final w = await widget.api.weekly();
      final m = await widget.api.mostBought();
      setState(() { _weekly = w; _most = m; });
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final weekly = (_weekly?['weekly_spending'] as Map?) ?? {};
    final most = (_most?['most_bought'] as List?) ?? [];
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('Purchase memory & analytics', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
      const Text('Confirmed purchases only. Unconfirmed extractions never count.'),
      const SizedBox(height: 12),
      const Text('Weekly spending', style: TextStyle(fontWeight: FontWeight.bold)),
      ...weekly.entries.map((e) => ListTile(title: Text(e.key), trailing: Text('\$${e.value}'))),
      const SizedBox(height: 12),
      const Text('Most-bought items', style: TextStyle(fontWeight: FontWeight.bold)),
      ...most.map((item) => ListTile(
            title: Text('${item['item_name']}'),
            trailing: Text('${item['occurrence_count']} purchases'),
          )),
    ]);
  }
}
