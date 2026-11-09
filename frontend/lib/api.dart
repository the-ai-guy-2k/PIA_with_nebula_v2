import 'dart:convert';
import 'package:http/http.dart' as http;

/// PIA backend client. Single user, no auth, no AI.
/// Base URL is set at build time with --dart-define=PIA_API_URL=...
/// Demo default is the Droplet backend, HTTP, certs null on purpose
/// (Tee explains certs later in the demo).
class PiaApi {
  PiaApi({String? baseUrl})
      : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'PIA_API_URL',
              defaultValue: 'http://138.68.226.24:8003',
            );

  final String baseUrl;

  Future<Map<String, dynamic>> uploadReceipt(List<int> bytes, String filename) async {
    final req = http.MultipartRequest('POST', Uri.parse('$baseUrl/api/receipts'))
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final resp = await http.Response.fromStream(await req.send());
    return _decode(resp);
  }

  Future<Map<String, dynamic>> extract(String evidenceId) async {
    final resp = await http.post(Uri.parse('$baseUrl/api/receipts/$evidenceId/extract'));
    return _decode(resp);
  }

  Future<Map<String, dynamic>> getExtraction(String extractionId) async {
    final resp = await http.get(Uri.parse('$baseUrl/api/extractions/$extractionId'));
    return _decode(resp);
  }

  Future<Map<String, dynamic>> correct(
      String extractionId, String? itemId, String field, String correctedValue) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/extractions/$extractionId/correct'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'item_id': itemId, 'field': field, 'corrected_value': correctedValue}),
    );
    return _decode(resp);
  }

  Future<Map<String, dynamic>> confirm(Map<String, dynamic> payload) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/purchases/confirm'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(payload),
    );
    return _decode(resp);
  }

  /// Product photo for an item: verified photo first, then Open Beauty
  /// Facts / Open Food Facts by barcode. Returns null when no photo is
  /// found — the UI shows a placeholder, never a wrong product's picture.
  Future<String?> productImage({String? upc, String? name}) async {
    final params = <String, String>{};
    if (upc != null && upc.isNotEmpty) params['upc'] = upc;
    if (name != null && name.isNotEmpty) params['name'] = name;
    if (params.isEmpty) return null;
    final uri = Uri.parse('$baseUrl/api/products/image')
        .replace(queryParameters: params);
    final resp = await http.get(uri);
    final body = _decode(resp);
    final url = body['image_url'];
    return url is String ? url : null;
  }

  Future<List<dynamic>> pantry() async {
    final resp = await http.get(Uri.parse('$baseUrl/api/pantry'));
    return (_decode(resp)['items'] as List<dynamic>);
  }

  Future<Map<String, dynamic>> pantryStatus(String id, String status) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/pantry/$id/status'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'status': status}),
    );
    return _decode(resp);
  }

  Future<Map<String, dynamic>> addPantryItem(String name, String quantity) async {
    final resp = await http.post(
      Uri.parse('$baseUrl/api/pantry'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'item_name': name, 'quantity': quantity}),
    );
    return _decode(resp);
  }

  Future<Map<String, dynamic>> weekly() async {
    final resp = await http.get(Uri.parse('$baseUrl/api/analytics/weekly'));
    return _decode(resp);
  }

  Future<Map<String, dynamic>> mostBought() async {
    final resp = await http.get(Uri.parse('$baseUrl/api/analytics/most-bought'));
    return _decode(resp);
  }

  Map<String, dynamic> _decode(http.Response resp) {
    final body = jsonDecode(resp.body) as Map<String, dynamic>;
    if (resp.statusCode >= 400) {
      throw Exception(body['reason'] ?? 'Request failed (${resp.statusCode})');
    }
    return body;
  }
}
