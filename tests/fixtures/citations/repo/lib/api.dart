class Api {
  // line 2
  // line 3
  // line 4
  Ref stockRef(int productId) =>
      _products.ref(path: '$productId/availability');
  // line 7
  // line 8
  // line 9
  // line 10
  Future<Stock> load() => _api.stockRef(id).get();
}
